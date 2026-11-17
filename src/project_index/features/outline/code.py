"""Python・TypeScript・JavaScript・package.json のアウトラインの取り出し。"""

from __future__ import annotations

import ast
import json
import re

from project_index.features.outline.types import CodeOutline, ExistingDescription
from project_index.shared.narrowing import is_dict

_EMPTY = CodeOutline(existing_description=None, functions=(), classes=(), imports=())
_SCRIPT_FUNCTION = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)"
)
_SCRIPT_ARROW = re.compile(r"^(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(")
_SCRIPT_CLASS = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"
)
_SCRIPT_IMPORT = re.compile(r"""(?:import\s+(?:[^'"]*?\s+from\s+)?|require\(\s*)['"]([^'"]+)['"]""")
_DOC_COMMENT = re.compile(r"\A\s*/\*\*(.*?)\*/", re.DOTALL)


def outline_python(text: str) -> CodeOutline:
    """Python のソースから最上位の関数・クラス・import とモジュールの docstring を取り出す。"""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # 読めないソースは定義の無いアウトラインにする（判定で no_definitions になる）
        return _EMPTY
    functions = tuple(
        node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    )
    classes = tuple(node.name for node in tree.body if isinstance(node, ast.ClassDef))
    imports: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            # 相対 import は `.` を付けたまま残す
            names = ["." * node.level + (node.module or "")]
        imports.extend(name for name in names if name not in imports)
    return CodeOutline(
        existing_description=_docstring_description(ast.get_docstring(tree)),
        functions=functions,
        classes=classes,
        imports=tuple(imports),
    )


def outline_script(text: str) -> CodeOutline:
    """TypeScript・JavaScript のソースから最上位の関数・クラス・import と先頭の説明を取り出す。"""
    functions: list[str] = []
    classes: list[str] = []
    for line in text.splitlines():
        # インデントの無い行だけを最上位の定義として見る
        function = _SCRIPT_FUNCTION.match(line) or _SCRIPT_ARROW.match(line)
        if function is not None:
            functions.append(function.group(1))
            continue
        klass = _SCRIPT_CLASS.match(line)
        if klass is not None:
            classes.append(klass.group(1))
    imports: list[str] = []
    for module in _SCRIPT_IMPORT.findall(text):
        if module not in imports:
            imports.append(module)
    comment = _DOC_COMMENT.match(text)
    docstring = None
    if comment is not None:
        # 各行の頭の `*` を除いて docstring と同じ形にする
        docstring = "\n".join(
            line.strip().lstrip("*").strip() for line in comment.group(1).splitlines()
        ).strip()
    return CodeOutline(
        existing_description=_docstring_description(docstring),
        functions=tuple(functions),
        classes=tuple(classes),
        imports=tuple(imports),
    )


def outline_package_json(text: str) -> CodeOutline:
    """package.json の `name`・`description` を既に持つ説明として取り出す。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _EMPTY
    if not is_dict(data):
        return _EMPTY
    description = data.get("description")
    if not isinstance(description, str):
        return _EMPTY
    name = data.get("name")
    return CodeOutline(
        existing_description=ExistingDescription(
            source="package_json",
            title=name if isinstance(name, str) else None,
            description=description,
        ),
        functions=(),
        classes=(),
        imports=(),
    )


def _docstring_description(docstring: str | None) -> ExistingDescription | None:
    """docstring の 1 行目をタイトル、空行の後を説明にする。"""
    if not docstring:
        return None
    first, _, rest = docstring.strip().partition("\n")
    detail = rest.strip()
    return ExistingDescription(source="docstring", title=first.strip(), description=detail or None)

"""プロンプトの YAML を、変数の表・テンプレート・例の組のセクションを持つ mdmark の Markdown にする。"""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING, Any

import pydantic

from project_index.features.prompt_doc.render import (
    HOOK_TEXT_WARN_CHARS,
    VALUE_MARK_PATTERN,
    build_environment,
    compile_parts,
    flatten_vars,
    flow_yaml,
    render_example,
)
from project_index.features.prompt_doc.types import (
    InvalidPrompt,
    PartSyntaxError,
    PromptDoc,
    PromptVar,
    PromptYamlError,
    RenderedExample,
)
from project_index.shared.yaml_io import YamlLoadError, load_yaml

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

# 全てのセクションの言語のタブを揃えて切り替える mdmark の group
LANG_TAB_GROUP = "lang"
# テンプレートの本文の `{{ 式 }}`
EXPR_PATTERN = re.compile(r"\{\{-?\s*(.*?)\s*-?\}\}")
# `{% for 変数 in 配列 %}` のループの変数と配列
FOR_PATTERN = re.compile(r"\{%-?\s*for\s+(\w+)\s+in\s+([\w.]+)")
# 式の先頭の変数の参照（`t.name | upper` の `t.name`）
REFERENCE_PATTERN = re.compile(r"[A-Za-z_]\w*(?:\.\w+)*")
# 値の無いセル
EMPTY_CELL = "-"
# 必須の変数のセル
REQUIRED_CELL = "✅"
# 「既定の例」のセクションの見出し
DEFAULT_EXAMPLE_NAME = "既定の例"
# コードブロックの区切りの最短の長さ
MIN_FENCE_LENGTH = 3


def convert_prompt(text: str) -> str:
    """プロンプトの YAML の文字列を読み、Markdown を返す。"""
    try:
        data = load_yaml(text)
    except YamlLoadError as error:
        msg = f"YAML を読み込めません: {error}"
        raise PromptYamlError(msg) from error
    try:
        doc = PromptDoc.model_validate(data)
    except pydantic.ValidationError as error:
        lines = [f"{_loc_path(item['loc'])}: {item['msg']}" for item in error.errors()]
        raise InvalidPrompt("\n".join(lines)) from error
    return prompt_to_markdown(doc)


def _loc_path(loc: Sequence[int | str]) -> str:
    """Pydantic の誤りの位置を `parts[0].texts` の形のキーのパスにする。"""
    path = ""
    for key in loc:
        # 配列の添字は `[n]`、キーは `.` でつなぐ
        if isinstance(key, int):
            path += f"[{key}]"
        else:
            path += f".{key}" if path else key
    return path


def prompt_to_markdown(doc: PromptDoc) -> str:
    """見出し・変数の表・テンプレート・例の組のセクションを並べる。"""
    paths = dict(flatten_vars(doc.vars))
    langs = languages(doc)
    compiled, syntax_errors = compile_parts(doc, env=build_environment())
    lines = [*_header(doc), "## 変数", "", *var_table(doc.vars), ""]
    # テンプレート: 部品ごとのセクションに言語のタブを置く
    lines += ["## テンプレート", ""]
    for part in doc.parts:
        lines += [f"### {part.id}", ""]
        badges = _part_badges(part.role, part.tags, part.when)
        if badges:
            lines += [badges, ""]
        part_errors = [error for error in syntax_errors if error.part_id == part.id]
        texts = {text.lang: text.text for text in part.texts}

        def template_body(
            lang: str,
            texts: dict[str, str] = texts,
            part_errors: list[PartSyntaxError] = part_errors,
        ) -> list[str]:
            """部品の 1 言語の本文（構文の誤りの注意書きを前に置く）。"""
            # when の誤りは全ての言語、本文の誤りはその言語のタブに出す
            errors = [e for e in part_errors if e.field in ("when", f"texts[{lang}]")]
            body = [line for error in errors for line in (*_syntax_caution(error), "")]
            if lang not in texts:
                return [*body, f"{lang} の本文はありません。"]
            return [*body, *_html_block(template_html(texts[lang], paths=paths))]

        lines += [*lang_tabs(langs, template_body), ""]
    # 例: 既定の例と examples の組を並べる（2 つ目以降は閉じて始める）
    lines += ["## 例", ""]
    groups: list[tuple[str, Mapping[str, Any]]] = [(DEFAULT_EXAMPLE_NAME, {})]
    groups += [(example.name, example.values) for example in doc.examples]
    for index, (name, values) in enumerate(groups):
        lines += [f"### {name}", ""]
        if index > 0:
            lines += ["<!-- section: closed -->", ""]

        def example_tab(lang: str, values: Mapping[str, Any] = values) -> list[str]:
            """例の組の 1 言語の描画の結果。"""
            rendered = render_example(
                doc, compiled=compiled, syntax_errors=syntax_errors, values=values, lang=lang
            )
            return example_body(rendered, doc=doc, lang=lang, paths=paths)

        lines += [*lang_tabs(langs, example_tab), ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def _header(doc: PromptDoc) -> list[str]:
    """見出し・バッジ・説明・タグと出力の行。"""
    lines = [f"# {doc.name}", "", f"`badge:kind: {doc.kind}` `badge:lang: {doc.lang}`", ""]
    if doc.description:
        lines += [doc.description, ""]
    if doc.tags:
        lines += ["タグ: " + " ".join(f"`badge:{tag}`" for tag in doc.tags), ""]
    if doc.output is not None:
        lines += [f"出力: {flow_yaml(doc.output)}", ""]
    return lines


def _part_badges(role: str | None, tags: Sequence[str], when: str | None) -> str:
    """部品の役割・タグ・使う条件のバッジの行。"""
    badges = [f"`badge:role: {role}`"] if role else []
    badges += [f"`badge:tag: {tag}`" for tag in tags]
    if when is not None:
        badges.append(f"`badge:when: {when.strip()}`")
    return " ".join(badges)


def _syntax_caution(error: PartSyntaxError) -> list[str]:
    """構文の誤りの注意書き。"""
    line = f"（{error.line} 行目）" if error.line is not None else ""
    return ["> [!CAUTION]", f"> {error.field}{line}の構文が誤っています: {error.message}"]


def _html_block(content: str) -> list[str]:
    """HTML を mdmark の埋め込みの HTML のブロックにする。"""
    # 中身の最も長いバッククォートの並びより長い区切りにする
    longest = max((len(run) for run in re.findall(r"`+", content)), default=0)
    fence = "`" * max(MIN_FENCE_LENGTH, longest + 1)
    return ["<!-- html -->", "", f"{fence}html", content, fence, "", "<!-- /html -->"]


def _cell(value: str) -> str:
    """表のセルの `|` と改行をエスケープする。"""
    return value.replace("|", "\\|").replace("\n", "<br>")


def var_table(vars_: Mapping[str, PromptVar]) -> list[str]:
    """変数のパスごとの行を持つ表の Markdown を作る。"""
    lines = ["| 変数 | 型 | 必須 | 例 | 説明 | 出典 |", "| --- | --- | --- | --- | --- | --- |"]
    for path, var in flatten_vars(vars_):
        example = f"`{flow_yaml(var.example)}`" if "example" in var.model_fields_set else EMPTY_CELL
        cells = [
            f"`{path}`",
            var.type or EMPTY_CELL,
            REQUIRED_CELL if var.required else EMPTY_CELL,
            example,
            var.description or EMPTY_CELL,
            var.source or EMPTY_CELL,
        ]
        lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    return lines


def _lookup(path: str, paths: Mapping[str, PromptVar]) -> PromptVar | None:
    """パスの定義を返す（`logs[]` のような配列の要素は配列の `items`）。"""
    if path in paths:
        return paths[path]
    array = paths.get(path.removesuffix("[]")) if path.endswith("[]") else None
    return array.items if array is not None else None


def _resolve_var(
    expr: str, aliases: Mapping[str, str], paths: Mapping[str, PromptVar]
) -> PromptVar | None:
    """式の先頭の変数の参照から、定義のある最も長いパスの定義を返す。"""
    found = REFERENCE_PATTERN.match(expr)
    if found is None:
        return None
    segments = found.group(0).split(".")
    # ループの変数は配列の要素のパスに読み替える
    if segments[0] in aliases:
        segments[0] = f"{aliases[segments[0]]}[]"
    # `t.name.upper` のように末尾が属性のときも、定義のある所まで縮める
    for end in range(len(segments), 0, -1):
        var = _lookup(".".join(segments[:end]), paths)
        if var is not None:
            return var
    return None


def _var_hint(var: PromptVar) -> str:
    """テンプレートの変数のツールチップの文。"""
    example = flow_yaml(var.example) if "example" in var.model_fields_set else EMPTY_CELL
    return f"{var.description}（型: {var.type or EMPTY_CELL}、例: {example}）"


def template_html(text: str, *, paths: Mapping[str, PromptVar]) -> str:
    """部品の本文をエスケープし、`{{ 変数 }}` に `data-hint` を付けた `<pre>` にする。"""
    aliases = {match.group(1): match.group(2) for match in FOR_PATTERN.finditer(text)}
    chunks: list[str] = []
    position = 0
    for match in EXPR_PATTERN.finditer(text):
        chunks.append(html.escape(text[position : match.start()]))
        expr = html.escape(match.group(0))
        var = _resolve_var(match.group(1), aliases, paths)
        # 定義のある変数だけにツールチップを付ける
        if var is None:
            chunks.append(expr)
        else:
            chunks.append(f'<span data-hint="{html.escape(_var_hint(var))}">{expr}</span>')
        position = match.end()
    chunks.append(html.escape(text[position:]))
    return "<pre><code>" + "".join(chunks) + "</code></pre>"


def _marked_html(marked: str, paths: Mapping[str, PromptVar]) -> str:
    """区切りで囲んだ値を、ツールチップ付きの `<mark>` にした HTML にする。"""

    def mark(match: re.Match[str]) -> str:
        path = match["path"]
        var = _lookup(path, paths)
        hint = f"{path}: {var.description}" if var is not None and var.description else path
        return f'<mark data-hint="{html.escape(hint)}">{match["value"]}</mark>'

    # 区切りは私用領域の文字のためエスケープで変わらない
    return VALUE_MARK_PATTERN.sub(mark, html.escape(marked))


def example_body(
    rendered: RenderedExample, *, doc: PromptDoc, lang: str, paths: Mapping[str, PromptVar]
) -> list[str]:
    """例の組を 1 言語で描画した結果を Markdown の行にする。"""
    # 描画できない組は理由だけを出す
    if rendered.problems:
        return [
            "> [!CAUTION]",
            "> この組は描画できません。",
            ">",
            *[f"> - {problem}" for problem in rendered.problems],
        ]
    lines: list[str] = []
    if doc.kind == "hook" and rendered.char_count > HOOK_TEXT_WARN_CHARS:
        lines += [
            "> [!WARNING]",
            f"> 注入する本文が {rendered.char_count:,} 字で、上限の {HOOK_TEXT_WARN_CHARS:,} 字を超えています。",
            "",
        ]
    for message in rendered.messages:
        if message.role is not None:
            lines += [f"**{message.role}**", ""]
        lines += [
            *_html_block(f"<pre><code>{_marked_html(message.marked, paths)}</code></pre>"),
            "",
        ]
    heading = f"注入する本文（{lang}）" if lang == doc.lang else f"{lang} の本文"
    unused = "、".join(rendered.unused) or "なし"
    lines.append(f"{heading}: {rendered.char_count:,} 字 / 使用しなかった部品: {unused}")
    return lines


def lang_tabs(languages: Sequence[str], body_of: Callable[[str], list[str]]) -> list[str]:
    """言語ごとの中身を言語のタブに並べる（言語が 1 つなら中身だけ）。"""
    if len(languages) == 1:
        return body_of(languages[0])
    lines = [f"<!-- tabs: group={LANG_TAB_GROUP} -->", ""]
    for lang in languages:
        lines += [f"#### {lang}", "", *body_of(lang), ""]
    lines.append("<!-- /tabs -->")
    return lines


def languages(doc: PromptDoc) -> list[str]:
    """部品の本文に出る言語を、注入する言語を先頭にして並べる。"""
    result = [doc.lang]
    for part in doc.parts:
        for text in part.texts:
            if text.lang not in result:
                result.append(text.lang)
    return result

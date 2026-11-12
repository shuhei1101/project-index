"""プロンプトの部品を Jinja2 で描画する（変数の値にパスを持たせ、描画結果の値を区切りで囲む）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import jinja2
from jinja2.environment import TemplateExpression

from project_index.features.prompt_doc.types import (
    PartSyntaxError,
    PromptDoc,
    PromptPart,
    PromptVar,
    RenderedExample,
    RenderedMessage,
    Role,
    VarType,
)
from project_index.shared.narrowing import is_dict, is_list
from project_index.shared.yaml_io import load_yaml

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

# `kind: llm` のメッセージを並べる順
ROLES: tuple[Role, ...] = ("system", "user", "assistant")
# `kind: hook` で描画した結果がこの字数を超えた組に注意を出す
HOOK_TEXT_WARN_CHARS = 1000
# 描画結果の変数の値を囲む区切り（私用領域の文字 U+E000 パス U+E001 値 U+E002）
VALUE_MARK_PATTERN = re.compile("\ue000(?P<path>[^\ue001]*)\ue001(?P<value>[^\ue002]*)\ue002")
# llm の同じ役割の部品の本文をつなぐ区切り
LLM_PART_SEPARATOR = "\n\n"
# フロー形式で引用符が要る文字（フローの区切り・コメント・キーの区切り・前後の空白・改行）
FLOW_QUOTE_PATTERN = re.compile(r"[,\[\]{}#\n]|: |:$|^\s|\s$")


class TracedStr(str):
    """変数のパスを持つ `str`（`{{ }}` の出力だけを `finalize` が区切りで囲む）。"""

    path: str

    def __new__(cls, value: str, *, path: str) -> TracedStr:
        obj = super().__new__(cls, value)
        obj.path = path
        return obj


class TracedInt(int):
    """変数のパスを持つ `int`。"""

    path: str

    def __new__(cls, value: int, *, path: str) -> TracedInt:
        obj = super().__new__(cls, value)
        obj.path = path
        return obj


class TracedFloat(float):
    """変数のパスを持つ `float`。"""

    path: str

    def __new__(cls, value: float, *, path: str) -> TracedFloat:
        obj = super().__new__(cls, value)
        obj.path = path
        return obj


TRACED_TYPES = (TracedStr, TracedInt, TracedFloat)


@dataclass(frozen=True, slots=True, kw_only=True)
class CompiledPart:
    """部品 1 件の `when` と言語ごとの本文のテンプレート。"""

    part: PromptPart
    when: TemplateExpression | None
    texts: dict[str, jinja2.Template]


def _flow_scalar(value: object) -> str:
    """スカラーをフロー形式の中で読み戻せる 1 語にする。"""
    if value is None or isinstance(value, bool | int | float):
        return json.dumps(value)
    text = str(value)
    # フローの区切りの文字を含まず、YAML として読み戻して同じ文字列になるものは引用符で囲まない
    if text and not FLOW_QUOTE_PATTERN.search(text) and load_yaml(text) == text:
        return text
    return json.dumps(text, ensure_ascii=False)


def flow_yaml(value: object) -> str:
    """値を YAML のフロー形式の 1 行にする。"""
    if is_dict(value):
        return "{" + ", ".join(f"{_flow_scalar(k)}: {flow_yaml(v)}" for k, v in value.items()) + "}"
    if is_list(value) or isinstance(value, tuple):
        # isinstance で絞った tuple は要素の型が Unknown になるため、object の並びとして読む
        items = cast("Iterable[object]", value)
        return "[" + ", ".join(flow_yaml(item) for item in items) + "]"
    return _flow_scalar(value)


def flatten_vars(
    vars_: Mapping[str, PromptVar], *, prefix: str = ""
) -> list[tuple[str, PromptVar]]:
    """`vars` を深さ優先で辿り、パスと定義の組にする。"""
    result: list[tuple[str, PromptVar]] = []
    for name, var in vars_.items():
        path = f"{prefix}{name}"
        result.append((path, var))
        # 配列の要素がオブジェクトなら、要素のキーを `{パス}[].` の下に並べる
        if var.type == "array" and var.items is not None and var.items.properties:
            result.extend(flatten_vars(var.items.properties, prefix=f"{path}[]."))
        # オブジェクトのキーは `{パス}.` の下に並べる
        if var.properties:
            result.extend(flatten_vars(var.properties, prefix=f"{path}."))
    return result


def _finalize(value: object) -> object:
    """パス付きの値だけを区切りで囲む。"""
    if isinstance(value, TRACED_TYPES):
        return f"\ue000{value.path}\ue001{value}\ue002"
    return value


def build_environment() -> jinja2.Environment:
    """部品を描画する Jinja2 の Environment を作る。"""
    return jinja2.Environment(
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,  # noqa: S701
        finalize=_finalize,
    )


def _matches(value: object, type_: VarType) -> bool:
    """値が定義の型に合うかを返す（`bool` は `integer`・`number` に合わない）。"""
    if type_ == "string":
        return isinstance(value, str)
    if type_ == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_ == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if type_ == "boolean":
        return isinstance(value, bool)
    if type_ == "array":
        return isinstance(value, list)
    return isinstance(value, dict)


def _trace(value: object, var: PromptVar, path: str, problems: list[str]) -> object:
    """値を定義と並べて辿り、型を確かめてパス付きの値にする。"""
    # 型が合わない: 理由を加え、その下は辿らない
    if var.type is not None and not _matches(value, var.type):
        problems.append(f"`{path}` は {var.type} ですが、`{flow_yaml(value)}` が入っています")
        return value
    # 配列: 要素の定義があれば `{パス}[]` で辿る
    if is_list(value):
        items = var.items
        if items is None:
            return value
        return [_trace(item, items, f"{path}[]", problems) for item in value]
    # オブジェクト: 定義のあるキーだけを `{パス}.{キー}` で辿る
    if is_dict(value):
        return {
            key: _trace(item, var.properties[key], f"{path}.{key}", problems)
            if isinstance(key, str) and key in var.properties
            else item
            for key, item in value.items()
        }
    return _traced_scalar(value, path)


def _traced_scalar(value: object, path: str) -> object:
    """文字列・整数・小数をパス付きの値にする（bool は継承できないため囲まない）。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return TracedStr(value, path=path)
    if isinstance(value, int):
        return TracedInt(value, path=path)
    if isinstance(value, float):
        return TracedFloat(value, path=path)
    return value


def build_values(
    vars_: Mapping[str, PromptVar], values: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """例の組の値を `example` で埋め、型を確かめてパス付きの値にする。"""
    # 組に無い変数を example で埋める（example: null も値として埋める）
    filled = dict(values)
    for name, var in vars_.items():
        if name not in filled and "example" in var.model_fields_set:
            filled[name] = var.example
    problems: list[str] = []
    result = {
        name: _trace(value, vars_[name], name, problems) if name in vars_ else value
        for name, value in filled.items()
    }
    return result, problems


def _strip_braces(expr: str) -> str:
    """前後の空白を除き、`{{ }}` で囲んだ式はそれを外す。"""
    stripped = expr.strip()
    if stripped.startswith("{{") and stripped.endswith("}}"):
        return stripped[2:-2]
    return stripped


def compile_parts(
    doc: PromptDoc, *, env: jinja2.Environment
) -> tuple[dict[str, CompiledPart], list[PartSyntaxError]]:
    """部品の本文と `when` をテンプレートにし、構文の誤りを集める。"""
    compiled: dict[str, CompiledPart] = {}
    errors: list[PartSyntaxError] = []
    for part in doc.parts:
        part_errors: list[PartSyntaxError] = []
        when: TemplateExpression | None = None
        if part.when is not None:
            try:
                when = env.compile_expression(_strip_braces(part.when))
            except jinja2.TemplateSyntaxError as error:
                part_errors.append(
                    PartSyntaxError(
                        part_id=part.id,
                        field="when",
                        line=error.lineno,
                        message=error.message or "",
                    )
                )
        texts: dict[str, jinja2.Template] = {}
        for text in part.texts:
            try:
                texts[text.lang] = env.from_string(text.text)
            except jinja2.TemplateSyntaxError as error:
                part_errors.append(
                    PartSyntaxError(
                        part_id=part.id,
                        field=f"texts[{text.lang}]",
                        line=error.lineno,
                        message=error.message or "",
                    )
                )
        # 誤りのある部品は結果から外す
        if part_errors:
            errors.extend(part_errors)
        else:
            compiled[part.id] = CompiledPart(part=part, when=when, texts=texts)
    return compiled, errors


def _syntax_problem(error: PartSyntaxError) -> str:
    """構文の誤りを描画できない理由の 1 行にする。"""
    line = f"（{error.line} 行目）" if error.line is not None else ""
    return f"部品 `{error.part_id}` の {error.field}{line}: {error.message}"


def _failed(problems: list[str]) -> RenderedExample:
    """描画できなかった組の結果を作る。"""
    return RenderedExample(messages=[], unused=[], char_count=0, problems=problems)


def _messages(doc: PromptDoc, rendered: list[tuple[Role | None, str]]) -> list[RenderedMessage]:
    """描画した本文をメッセージにまとめる。"""
    # llm 以外: 全てをつないで 1 件にする
    if doc.kind != "llm":
        return [_message(None, "".join(text for _, text in rendered))]
    # llm: 役割ごとにつなぎ、空でないものを ROLES の順に並べる（役割の無い部品は最後に置く）
    messages: list[RenderedMessage] = []
    for role in (*ROLES, None):
        joined = LLM_PART_SEPARATOR.join(text for part_role, text in rendered if part_role == role)
        if joined:
            messages.append(_message(role, joined))
    return messages


def _message(role: Role | None, marked: str) -> RenderedMessage:
    """区切り付きの本文から、区切りを外した本文を持つメッセージを作る。"""
    return RenderedMessage(
        role=role, text=VALUE_MARK_PATTERN.sub(lambda m: m["value"], marked), marked=marked
    )


def render_example(
    doc: PromptDoc,
    *,
    compiled: Mapping[str, CompiledPart],
    syntax_errors: Sequence[PartSyntaxError],
    values: Mapping[str, Any],
    lang: str,
) -> RenderedExample:
    """例の組を 1 言語で描画し、メッセージ・使わなかった部品・字数を返す。"""
    # 構文の誤った部品があると注入文を作れない
    if syntax_errors:
        return _failed([_syntax_problem(error) for error in syntax_errors])
    traced, problems = build_values(doc.vars, values)
    if problems:
        return _failed(problems)
    # 部品を並び順に描画する
    unused: list[str] = []
    rendered: list[tuple[Role | None, str]] = []
    for part in doc.parts:
        compiled_part = compiled[part.id]
        try:
            # when が偽: 使わない
            if compiled_part.when is not None and not compiled_part.when(**traced):
                unused.append(part.id)
                continue
            template = compiled_part.texts.get(lang)
            # その言語の本文が無い: 使わない
            if template is None:
                unused.append(f"{part.id}（{lang} の本文なし）")
                continue
            rendered.append((part.role, template.render(**traced)))
        except jinja2.UndefinedError as error:
            return _failed([f"未定義の変数: {error.message}"])
        # 描画中のどの例外も、組の注意書きにして他の組の描画を続ける（利用者のテンプレートはサンドボックスで動かさず、送る例外を絞れない）
        except Exception as error:  # noqa: BLE001
            return _failed([f"部品 `{part.id}` を描画できません: {type(error).__name__}: {error}"])
    messages = _messages(doc, rendered)
    return RenderedExample(
        messages=messages,
        unused=unused,
        char_count=sum(len(message.text) for message in messages),
        problems=[],
    )

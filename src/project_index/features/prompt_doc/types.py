"""`project-index prompt-doc` が読むプロンプトの YAML のモデルと、描画の結果・例外の型。

サーバーが起動のときに読むプロンプトの違反の型も持つ。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

VarType = Literal["string", "integer", "number", "boolean", "array", "object"]
Role = Literal["system", "user", "assistant"]


class PromptVar(BaseModel):
    """`vars` の 1 件（入れ子の `items`・`properties` を含む）。"""

    model_config = ConfigDict(extra="ignore")

    # 無ければ型を確かめない
    type: VarType | None = None
    required: bool = False
    description: str = ""
    # 無いことと `example: null` は `model_fields_set` で分ける
    example: Any = None
    source: str | None = None
    items: PromptVar | None = None
    properties: dict[str, PromptVar] = Field(default_factory=dict)


class PromptText(BaseModel):
    """部品の 1 言語の本文。"""

    model_config = ConfigDict(extra="ignore")

    lang: str
    text: str


class PromptPart(BaseModel):
    """`parts` の 1 件。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    role: Role | None = None
    tags: list[str] = Field(default_factory=list[str])
    # Jinja2 の式。偽なら部品を使わない
    when: str | None = None
    texts: list[PromptText] = Field(min_length=1)


class PromptExample(BaseModel):
    """`examples` の 1 件。"""

    model_config = ConfigDict(extra="ignore")

    name: str
    values: dict[str, Any] = Field(default_factory=dict[str, Any])


class PromptDoc(BaseModel):
    """プロンプトの YAML 1 件のうち変換に使うキー。"""

    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    # `llm` はメッセージに分け、`hook` は字数の注意を出す
    kind: Literal["llm", "hook", "instructions", "tool"]
    # 注入する言語
    lang: str
    tags: list[str] = Field(default_factory=list[str])
    output: Any = None
    vars: dict[str, PromptVar] = Field(default_factory=dict[str, PromptVar])
    parts: list[PromptPart]
    examples: list[PromptExample] = Field(default_factory=list[PromptExample])


@dataclass(frozen=True, slots=True, kw_only=True)
class RenderedMessage:
    """例の組を 1 言語で描画した本文 1 件。"""

    role: Role | None
    # 注入する文字列と同じ本文（字数を数える）
    text: str
    # 変数の値を `VALUE_MARK_PATTERN` の区切りで囲んだ本文（エスケープ前）
    marked: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RenderedExample:
    """例の組を 1 言語で描画した結果（`problems` があるときは `messages` が空）。"""

    messages: list[RenderedMessage]
    unused: list[str]
    char_count: int
    problems: list[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class PartSyntaxError:
    """テンプレートにできなかった部品の本文か `when` 1 件。"""

    part_id: str
    # `when` か `texts[{lang}]`
    field: str
    line: int | None
    message: str


class PromptDocError(Exception):
    """`project-index prompt-doc` が終了コード 1 で終える例外の基底。"""


class PromptYamlError(PromptDocError):
    """標準入力が YAML として読めない。"""


class InvalidPrompt(PromptDocError):  # noqa: N818
    """変換に使うキーが無いか型が違う。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class PromptProblem:
    """起動のときに読んだプロンプトの YAML の違反 1 件。"""

    # 違反した YAML の絶対パス。無いファイルはあるはずのパス
    file: Path
    # 違反したキーのパス。ファイル全体の違反は `$`
    path: str
    reason: str

    def line(self) -> str:
        """`{ファイル}: {キーのパス}: {理由}` の 1 行にする。"""
        return f"{self.file}: {self.path}: {self.reason}"


class PromptInvalidError(Exception):
    """起動のときに読むプロンプトの YAML が無い・読めない・スキーマに違反する・描画できない。"""

    def __init__(self, problems: list[PromptProblem]) -> None:
        super().__init__("\n".join(problem.line() for problem in problems))
        self.problems = problems

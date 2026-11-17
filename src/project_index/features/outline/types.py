"""アウトラインと次の段階へ進む理由の型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

type DescriptionSource = Literal["front_matter", "docstring", "package_json"]


class NextStageReason(StrEnum):
    """アウトラインだけでは名前と説明を決めにくい理由。"""

    FEW_HEADINGS = "few_headings"
    MOSTLY_CODE = "mostly_code"
    NOT_JAPANESE = "not_japanese"
    NO_DEFINITIONS = "no_definitions"
    UNSUPPORTED_FORMAT = "unsupported_format"


@dataclass(frozen=True)
class ExistingDescription:
    """ファイルが既に持つ説明。"""

    source: DescriptionSource
    title: str | None
    description: str | None


@dataclass(frozen=True)
class MarkdownOutline:
    """Markdown 1 つから取り出したアウトライン。"""

    existing_description: ExistingDescription | None
    headings: tuple[str, ...]
    # フロントマターを除いた行のうち、フェンスの行を含むコードブロックの行の割合
    code_block_ratio: float
    code_languages: tuple[str, ...]
    link_count: int
    image_count: int
    # コードブロックの外の、空白と記号を除いた文字のうちひらがな・カタカナ・漢字の割合
    japanese_ratio: float


@dataclass(frozen=True)
class CodeOutline:
    """コード 1 つから取り出したアウトライン。"""

    existing_description: ExistingDescription | None
    functions: tuple[str, ...]
    classes: tuple[str, ...]
    imports: tuple[str, ...]


@dataclass(frozen=True)
class FileOutline:
    """`project-index outline` が 1 行の JSON にするファイル 1 つ分の結果。"""

    path: str
    size: int
    existing_description: ExistingDescription | None
    headings: tuple[str, ...]
    code_block_ratio: float
    code_languages: tuple[str, ...]
    link_count: int
    image_count: int
    japanese_ratio: float
    functions: tuple[str, ...]
    classes: tuple[str, ...]
    imports: tuple[str, ...]
    next_stage: bool
    reasons: tuple[NextStageReason, ...]

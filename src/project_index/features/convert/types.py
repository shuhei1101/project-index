"""変換の結果と変換の失敗の型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ConvertFailure:
    """変換できなかった理由。"""

    reason: Literal["timeout", "exit", "not_runnable", "invalid_yaml"]
    kind: str
    detail: str
    script: str | None = None
    file: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True)
class Converted:
    """`converters[]` のスクリプトが出した Markdown か、変換の失敗。"""

    markdown: str
    failure: ConvertFailure | None = None

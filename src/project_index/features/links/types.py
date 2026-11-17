"""本文が指すファイルと取り出し方の型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LinkVia(StrEnum):
    """指す先を取り出した方法。"""

    LINK = "link"
    PATH = "path"


@dataclass(frozen=True)
class LinkTarget:
    """指される側のファイル 1 つ。"""

    path: str
    via: LinkVia


@dataclass(frozen=True)
class FileLinks:
    """指す側のファイル 1 つと、その指す先（`path` の昇順で重複なし）。"""

    path: str
    targets: tuple[LinkTarget, ...]

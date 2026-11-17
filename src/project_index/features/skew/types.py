"""数える行・ほぼ同じ description の組・偏ったタグ・結果と入力を読めない例外の型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class MetadataRow:
    """管理用の YAML の行か行の案 1 つ。"""

    # `--root` からのパス（管理用の YAML のフォルダ + 行の `path`）
    path: str
    description: str | None
    # タグの名前（重複なし、出た順）
    tags: tuple[str, ...]


@dataclass(frozen=True)
class SimilarPair:
    """類似度がしきい値以上の 2 行。"""

    # 2 行のパス（昇順）
    paths: tuple[str, str]
    similarity: float


@dataclass(frozen=True)
class SingletonTag:
    """1 行にだけ付いているタグとその行。"""

    tag: str
    path: str


@dataclass(frozen=True)
class DominantTag:
    """半数以上の行に付いているタグとその数。"""

    tag: str
    count: int


@dataclass(frozen=True)
class SkewResult:
    """`project-index skew` が JSON にする結果。"""

    rows: int
    # similarity の降順、同じ値はパスの昇順
    similar_descriptions: tuple[SimilarPair, ...]
    # タグの昇順
    singleton_tags: tuple[SingletonTag, ...]
    # count の降順、同じ数はタグの昇順
    dominant_tags: tuple[DominantTag, ...]


class SkewInputError(Exception):
    """`--files-yaml` か `--draft` のファイルが無いか読めない。"""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason

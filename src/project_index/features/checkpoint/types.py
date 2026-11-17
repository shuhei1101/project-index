"""確認の時点・起点・変わったファイルの一覧の型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CHECKPOINT_KEY = "checkpoint"


class BaseKind(StrEnum):
    """変わったファイルを比べる起点にしたもの。"""

    CHECKPOINT_COMMIT = "checkpoint_commit"
    CHECKPOINT_TIME = "checkpoint_time"
    FILES_YAML_COMMIT = "files_yaml_commit"
    FILES_YAML_MTIME = "files_yaml_mtime"


@dataclass(frozen=True)
class ReviewedFile:
    """見直した未 commit のファイルとその中身のハッシュ。"""

    path: str
    sha256: str


@dataclass(frozen=True)
class Checkpoint:
    """管理用の YAML の `checkpoint` の値。"""

    # Git の配信元は commit と reviewed、Git 管理外は checked_at だけを持つ
    commit: str | None
    reviewed: tuple[ReviewedFile, ...] = ()
    checked_at: datetime | None = None


@dataclass(frozen=True)
class ChangedBase:
    """変わったファイルを比べた起点。"""

    kind: BaseKind
    value: str


@dataclass(frozen=True)
class ChangedResult:
    """`project-index changed` が JSON にする結果。"""

    base: ChangedBase
    files: tuple[str, ...]
    # 記録した commit がリポジトリに無く起点を切り替えたとき、その commit の ID
    missing_commit: str | None = None


class FilesYamlNotFoundError(Exception):
    """`--files-yaml` のファイルが無いことを表す。"""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path}: 管理用の YAML がありません")
        self.path = path


class ReviewedFileNotFoundError(Exception):
    """`--reviewed` のファイルが無いことを表す。"""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path}: ファイルがありません")
        self.path = path

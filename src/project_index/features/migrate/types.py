"""設定の移し替えの手順・対象・例外の型と終了コード。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal

from project_index.main import EXIT_CONFIG_INVALID

# パッケージの中の手順のフォルダ。`{MIGRATIONS_DIR}/{kind}/{バージョン}/steps.yaml` を読む
MIGRATIONS_DIR = "migrations"
STEPS_FILE = "steps.yaml"
# 対象と同じフォルダに置くバックアップの名前。時刻は `%Y%m%dT%H%M%S`
BACKUP_FORMAT = "{name}.bak-{time}"
BACKUP_TIME_FORMAT = "%Y%m%dT%H%M%S"
EXIT_MIGRATION_FAILED = 4
EXIT_DESTRUCTIVE_BLOCKED = 5
EXIT_CONFIG_NEWER = 6


@dataclass(frozen=True)
class MigrationStep:
    """`steps.yaml` の 1 行。"""

    version: str
    op: Literal["rename", "add", "delete", "lift", "unwrap"]
    path: str
    description: str
    to: str | None = None
    value: Any = None
    match: dict[str, Any] | None = None
    take: str | None = None

    @property
    def destructive(self) -> bool:
        """値を捨てる手順か（値を指さない削除）。"""
        return self.op == "delete" and self.value is None


@dataclass(frozen=True)
class MigrationTarget:
    """移し替える設定のファイルと種類。"""

    kind: Literal["settings", "project-index"]
    file: Path
    current: str


class MigrationError(Exception):
    """`project-index migrate` が終了コードに対応させる例外の基底。"""

    exit_code: ClassVar[int]


class MigrationConfigInvalidError(MigrationError):
    """対象の設定が無い・読めない・`version` が無い。"""

    exit_code = EXIT_CONFIG_INVALID


class MigrationFailedError(MigrationError):
    """手順を当てられない、新しいスキーマに違反する、書く前にファイルが変わった。"""

    exit_code = EXIT_MIGRATION_FAILED


class DestructiveStepBlockedError(MigrationError):
    """破壊的な手順があり `--allow-destructive` が無い。"""

    exit_code = EXIT_DESTRUCTIVE_BLOCKED


class ConfigNewerError(MigrationError):
    """対象の `version` が参照できるバージョンより新しい。"""

    exit_code = EXIT_CONFIG_NEWER

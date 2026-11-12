"""`project-index migrate` の対象の決定・手順の一覧・適用。"""
# pyright: reportUnknownArgumentType=warning

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from project_index.features.admin.service import version_state
from project_index.features.migrate.steps import apply_step, load_steps
from project_index.features.migrate.types import (
    BACKUP_FORMAT,
    BACKUP_TIME_FORMAT,
    ConfigNewerError,
    DestructiveStepBlockedError,
    MigrationConfigInvalidError,
    MigrationFailedError,
    MigrationStep,
    MigrationTarget,
)
from project_index.features.settings.query import (
    SETTINGS_VERSION,
    config_path,
    validate_terminal_config,
)
from project_index.features.sources.service import validate_source_config
from project_index.features.sources.types import SOURCE_CONFIG_VERSION
from project_index.shared.files import replace_file
from project_index.shared.hashing import content_hash
from project_index.shared.paths import normalize_path
from project_index.shared.yaml_io import YamlLoadError, dump_roundtrip, load_roundtrip, load_yaml

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from pathlib import Path

    from ruamel.yaml.comments import CommentedMap

    from project_index.shared.errors import Violation

logger = logging.getLogger(__name__)

SETUP_GUIDE = "手順で移せない設定です。/project-index:setup で移し替えてください"


def resolve_target(source: str | None, *, env: Mapping[str, str]) -> MigrationTarget:
    """`--source` の有無で移し替える設定を決める。"""
    if source is not None:
        return MigrationTarget(
            kind="project-index", file=normalize_path(source), current=SOURCE_CONFIG_VERSION
        )
    return MigrationTarget(kind="settings", file=config_path(env), current=SETTINGS_VERSION)


def plan_migration(target: MigrationTarget) -> tuple[CommentedMap, list[MigrationStep]]:
    """対象の `version` を読み、当てる手順を求める。"""
    try:
        data = load_roundtrip(target.file.read_text(encoding="utf-8"), file=str(target.file))
    except (OSError, YamlLoadError) as error:
        msg = f"{target.file}: {error}"
        raise MigrationConfigInvalidError(msg) from error
    version = str(data["version"]) if "version" in data else ""
    if not version.isdecimal():
        msg = f"{target.file}: version が整数の文字列で記載されていません"
        raise MigrationConfigInvalidError(msg)
    state = version_state(version, target.current)
    # 新しすぎる設定は移し替えない
    if state == "newer":
        msg = (
            f"{target.file}: 設定のバージョン {version} が project-index で読み込める {target.current}"
            " より新しい。project-index を更新してください"
        )
        raise ConfigNewerError(msg)
    if state == "current":
        return data, []
    return data, load_steps(target.kind, mine=version, current=target.current)


def _violations(target: MigrationTarget, value: dict[str, Any]) -> list[Violation]:
    """当てた結果を、対象の種類の新しいスキーマで確かめる。"""
    if target.kind == "settings":
        return validate_terminal_config(value)
    return validate_source_config(value, root=target.file.parent)


def apply_migration(
    target: MigrationTarget,
    data: CommentedMap,
    steps: list[MigrationStep],
    *,
    allow_destructive: bool,
    now: datetime,
) -> Path:
    """手順を全て当てて新しいスキーマで検証し、バックアップを取ってから 1 回だけ書き込む。"""
    # 破壊的な手順は、許されたときだけ当てる
    destructive = [step for step in steps if step.destructive]
    if destructive and not allow_destructive:
        lines = [f"{step.version}: {step.description}" for step in destructive]
        raise DestructiveStepBlockedError(
            "\n".join(["破壊的な手順があります", *lines, "--allow-destructive で適用できます"])
        )
    # 読んだ後にファイルが変わっていないかを、読んだ内容との比較とハッシュで確かめる
    original = target.file.read_text(encoding="utf-8")
    if dump_roundtrip(load_roundtrip(original)) != dump_roundtrip(data):
        msg = f"{target.file}: 読み込んだ後に変わったため書き換えません"
        raise MigrationFailedError(msg)
    digest = content_hash(original)
    for step in steps:
        apply_step(data, step)
    previous_version = str(data["version"])
    data["version"] = DoubleQuotedScalarString(target.current)
    text = dump_roundtrip(data)
    violations = _violations(target, load_yaml(text))
    # 当てた結果が新しいスキーマに違反するときは書かない
    if violations:
        lines = [f"{v.path}: {v.rule}" for v in violations]
        if target.kind == "project-index":
            lines.append(SETUP_GUIDE)
        raise MigrationFailedError("\n".join(lines))
    if content_hash(target.file.read_text(encoding="utf-8")) != digest:
        msg = f"{target.file}: 読み込んだ後に変わったため書き換えません"
        raise MigrationFailedError(msg)
    backup = target.file.with_name(
        BACKUP_FORMAT.format(name=target.file.name, time=now.strftime(BACKUP_TIME_FORMAT))
    )
    replace_file(backup, original)
    replace_file(target.file, text)
    logger.info(
        "設定を移し替えた（%s・%s から %s・バックアップ %s）",
        target.file,
        previous_version,
        target.current,
        backup,
    )
    return backup

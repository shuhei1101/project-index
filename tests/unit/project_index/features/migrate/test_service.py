from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from project_index.features.migrate.service import apply_migration, plan_migration, resolve_target
from project_index.features.migrate.types import (
    ConfigNewerError,
    DestructiveStepBlockedError,
    MigrationConfigInvalidError,
    MigrationFailedError,
    MigrationStep,
    MigrationTarget,
)
from project_index.shared.yaml_io import load_roundtrip, load_yaml

SETTINGS_V1 = 'version: "1"\nclone: /x\nlog_dir: /logs\n'
NOW = datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)
BACKUP_NAME = "settings.yaml.bak-20261029T120000"


def _step(op: str, path: str, **overrides: Any) -> MigrationStep:
    """手順 1 つを作る。"""
    values: dict[str, Any] = {
        "version": "2",
        "op": op,
        "path": path,
        "to": None,
        "value": None,
        "description": "手順",
    }
    values.update(overrides)
    return MigrationStep(**values)


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    """`version: "1"` の端末の設定を書いたファイルを返す。"""
    path = tmp_path / "settings.yaml"
    path.write_text(SETTINGS_V1, encoding="utf-8")
    return path


def _target(file: Path, current: str = "2") -> MigrationTarget:
    """端末の設定の移し替えの対象を作る。"""
    return MigrationTarget(kind="settings", file=file, current=current)


def test_resolve_target() -> None:
    """端末の設定を対象にする（正常系）。"""
    # 実行
    target = resolve_target(None, env={"PROJECT_INDEX_CONFIG": "/tmp/s.yaml"})
    # 検証
    assert target.kind == "settings"
    assert target.file == Path("/tmp/s.yaml")


def test_resolve_target_when_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """配信元の設定を対象にする（正常系）。"""
    # 準備
    monkeypatch.setenv("HOME", str(tmp_path))
    # 実行
    target = resolve_target("~/repo/a/project-index.yaml", env={})
    # 検証
    assert target.kind == "project-index"
    assert target.file == tmp_path / "repo" / "a" / "project-index.yaml"


def test_plan_migration(settings_file: Path, write_steps: Callable[..., None]) -> None:
    """当てる手順を返す（正常系）。"""
    # 準備
    write_steps(
        "settings",
        "2",
        [{"op": "rename", "path": "log_dir", "to": "state_dir", "description": "改名"}],
    )
    # 実行
    data, steps = plan_migration(_target(settings_file))
    # 検証
    assert data["version"] == "1"
    assert [step.op for step in steps] == ["rename"]


def test_plan_migration_when_current(settings_file: Path, write_steps: Callable[..., None]) -> None:
    """同じバージョンなら手順は空（正常系）。"""
    # 準備
    write_steps("settings", "2", [{"op": "delete", "path": "log_dir", "description": "削除"}])
    # 実行
    _, steps = plan_migration(_target(settings_file, current="1"))
    # 検証
    assert steps == []


def test_plan_migration_when_newer(tmp_path: Path) -> None:
    """新しすぎる設定（異常系）。"""
    # 準備
    path = tmp_path / "settings.yaml"
    path.write_text('version: "9"\nclone: /x\n', encoding="utf-8")
    # 実行・検証
    with pytest.raises(ConfigNewerError):
        plan_migration(_target(path, current="1"))


def test_plan_migration_when_no_version(tmp_path: Path) -> None:
    """version が無い（異常系）。"""
    # 準備
    path = tmp_path / "settings.yaml"
    path.write_text("clone: ~/project-index\n", encoding="utf-8")
    # 実行・検証
    with pytest.raises(MigrationConfigInvalidError):
        plan_migration(_target(path))


@pytest.mark.usefixtures("settings_version_2")
def test_apply_migration(settings_file: Path) -> None:
    """手順を当ててバックアップを取る（正常系）。"""
    # 準備
    data = load_roundtrip(settings_file.read_text(encoding="utf-8"))
    steps = [_step("rename", "log_dir", to="state_dir")]
    # 実行
    backup = apply_migration(_target(settings_file), data, steps, allow_destructive=False, now=NOW)
    # 検証
    assert load_yaml(settings_file.read_text(encoding="utf-8")) == {
        "version": "2",
        "clone": "/x",
        "state_dir": "/logs",
    }
    assert backup == settings_file.parent / BACKUP_NAME
    assert backup.read_text(encoding="utf-8") == SETTINGS_V1


@pytest.mark.usefixtures("settings_version_2")
def test_apply_migration_when_record(settings_file: Path) -> None:
    """手順が空なら version だけを書き換える（正常系）。"""
    # 準備
    data = load_roundtrip(settings_file.read_text(encoding="utf-8"))
    # 実行
    backup = apply_migration(_target(settings_file), data, [], allow_destructive=False, now=NOW)
    # 検証
    assert load_yaml(settings_file.read_text(encoding="utf-8")) == {
        "version": "2",
        "clone": "/x",
        "log_dir": "/logs",
    }
    assert backup.read_text(encoding="utf-8") == SETTINGS_V1


@pytest.mark.usefixtures("settings_version_2")
def test_apply_migration_when_destructive(settings_file: Path) -> None:
    """破壊的な手順で止める（異常系）。"""
    # 準備
    data = load_roundtrip(settings_file.read_text(encoding="utf-8"))
    steps = [_step("delete", "log_dir")]
    # 実行・検証
    with pytest.raises(DestructiveStepBlockedError):
        apply_migration(_target(settings_file), data, steps, allow_destructive=False, now=NOW)
    assert settings_file.read_text(encoding="utf-8") == SETTINGS_V1
    assert list(settings_file.parent.glob("*.bak-*")) == []


@pytest.mark.usefixtures("settings_version_2")
def test_apply_migration_when_invalid_result(settings_file: Path) -> None:
    """新しいスキーマに違反する（異常系）。"""
    # 準備
    data = load_roundtrip(settings_file.read_text(encoding="utf-8"))
    steps = [_step("delete", "clone")]
    # 実行・検証
    with pytest.raises(MigrationFailedError):
        apply_migration(_target(settings_file), data, steps, allow_destructive=True, now=NOW)
    assert settings_file.read_text(encoding="utf-8") == SETTINGS_V1


@pytest.mark.usefixtures("settings_version_2")
def test_apply_migration_when_changed(settings_file: Path) -> None:
    """読んだ後に変わったファイルを書かない（異常系）。"""
    # 準備
    data = load_roundtrip(settings_file.read_text(encoding="utf-8"))
    changed = 'version: "1"\nclone: /changed\nlog_dir: /logs\n'
    settings_file.write_text(changed, encoding="utf-8")
    steps = [_step("rename", "log_dir", to="state_dir")]
    # 実行・検証
    with pytest.raises(MigrationFailedError):
        apply_migration(_target(settings_file), data, steps, allow_destructive=False, now=NOW)
    assert settings_file.read_text(encoding="utf-8") == changed


def test_apply_migration_when_source_needs_setup(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """手順で移せない配信元の設定（異常系）。"""
    # 準備
    legacy = (
        'version: "1"\n'
        "name: sample\n"
        "documents:\n"
        "  - id: rules\n"
        "    type: markdown\n"
        "    paths: [docs/rule/*.yaml]\n"
        "    schema: schemas/rule.schema.yaml\n"
    )
    write_files(
        tmp_path,
        {"project-index.yaml": legacy, "schemas/rule.schema.yaml": "title: rule\ntype: object\n"},
    )
    target = MigrationTarget(kind="project-index", file=tmp_path / "project-index.yaml", current="2")
    data, steps = plan_migration(target)
    # 実行・検証
    with pytest.raises(MigrationFailedError) as exc_info:
        apply_migration(target, data, steps, allow_destructive=False, now=NOW)
    assert "documents[0].type" in str(exc_info.value)
    assert "/project-index:setup" in str(exc_info.value)
    assert target.file.read_text(encoding="utf-8") == legacy

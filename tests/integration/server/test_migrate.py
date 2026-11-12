from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from project_index.__main__ import main
from project_index.shared.yaml_io import load_yaml

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

SETTINGS_V1 = 'version: "1"\nclone: /x\nlog_dir: /logs\n'
RENAME_LOG_DIR = {"op": "rename", "path": "log_dir", "to": "state_dir", "description": "改名"}


@pytest.fixture
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`version: "1"` の端末の設定を書き、`PROJECT_INDEX_CONFIG` で指す。"""
    path = tmp_path / "settings.yaml"
    path.write_text(SETTINGS_V1, encoding="utf-8")
    monkeypatch.setenv("PROJECT_INDEX_CONFIG", str(path))
    return path


def _backups(folder: Path) -> list[Path]:
    """フォルダのバックアップのファイルを集める。"""
    return sorted(folder.glob("*.bak-*"))


@pytest.mark.usefixtures("versions_2")
def test_normal(
    settings_file: Path,
    write_steps: Callable[..., None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """古い端末の設定に手順を当て、バックアップを残して version を上げる（正常系）。"""
    # 準備
    write_steps("settings", "2", [RENAME_LOG_DIR])
    # 実行
    plan_code = main(["migrate", "--plan"])
    plan_out = capsys.readouterr().out
    unchanged = settings_file.read_text(encoding="utf-8")
    code = main(["migrate"])
    capsys.readouterr()
    after = settings_file.read_text(encoding="utf-8")
    again_code = main(["migrate"])
    again_out = capsys.readouterr().out
    # 検証
    backups = _backups(settings_file.parent)
    assert plan_code == 0
    assert plan_out.splitlines() == ["2: 改名"]
    assert unchanged == SETTINGS_V1
    assert code == 0
    assert load_yaml(after) == {"version": "2", "clone": "/x", "state_dir": "/logs"}
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == SETTINGS_V1
    assert again_code == 0
    assert "移し替えは要りません" in again_out
    assert settings_file.read_text(encoding="utf-8") == after


@pytest.mark.usefixtures("versions_2")
def test_normal_when_record_only(settings_file: Path, write_steps: Callable[..., None]) -> None:
    """`--record` で手順を当てずに version だけを書き換える（正常系）。"""
    # 準備
    write_steps("settings", "2", [RENAME_LOG_DIR])
    # 実行
    code = main(["migrate", "--record"])
    # 検証
    assert code == 0
    assert load_yaml(settings_file.read_text(encoding="utf-8")) == {
        "version": "2",
        "clone": "/x",
        "log_dir": "/logs",
    }


def test_normal_when_source_config(tmp_path: Path, settings_file: Path) -> None:
    """`--source --allow-destructive` で配信元の `project-index.yaml` に手順を当てる（正常系）。"""
    # 準備
    folder = tmp_path / "sample"
    (folder / "schemas").mkdir(parents=True)
    (folder / "schemas" / "rule.schema.yaml").write_text("type: object\n", encoding="utf-8")
    config = folder / "project-index.yaml"
    (folder / "tags.yaml").write_text("python: Python の規約\n", encoding="utf-8")
    config.write_text(
        'version: "1"\nname: sample\ndescription: 説明\ntags: tags.yaml\n'
        "documents:\n"
        "  - id: rules\n"
        "    type: yaml\n"
        "    paths: [docs/rule/*.yaml]\n"
        "    schema: schemas/rule.schema.yaml\n"
        "    metadata:\n"
        "      name: {type: ref, field: title}\n"
        "      alias_type: {type: custom, value: term}\n",
        encoding="utf-8",
    )
    # 実行
    code = main(["migrate", "--source", str(config), "--allow-destructive"])
    # 検証
    value = load_yaml(config.read_text(encoding="utf-8"))
    row = value["documents"][0]
    assert code == 0
    assert value["version"] == "3"
    assert "tags" not in value
    assert (folder / "tags.yaml").exists()
    assert "type" not in row
    assert row["metadata"] == {"name": "title"}
    assert row["alias_type"] == "term"
    assert settings_file.read_text(encoding="utf-8") == SETTINGS_V1


def test_error_when_source_config_unmigratable(
    tmp_path: Path, settings_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """配信元の設定に移せない設定があると、書き換えず終了コード 4 で止める（異常系）。"""
    # 準備
    folder = tmp_path / "sample"
    (folder / "schemas").mkdir(parents=True)
    (folder / "schemas" / "rule.schema.yaml").write_text("type: object\n", encoding="utf-8")
    config = folder / "project-index.yaml"
    text = (
        'version: "1"\nname: sample\n'
        "documents:\n"
        "  - id: rules\n"
        "    type: yaml\n"
        "    paths: [docs/rule/*.yaml]\n"
        "    schema: schemas/rule.schema.yaml\n"
        "    metadata:\n"
        "      name: {type: ref, field: title}\n"
        "  - id: notes\n"
        "    type: markdown\n"
        "    paths: [docs/note/*.md]\n"
        "    schema: schemas/rule.schema.yaml\n"
        "    defaults:\n"
        "      - paths: [docs/**]\n"
        "        tags: [doc]\n"
        "  - id: others\n"
        "    paths: [docs/other/*.yaml]\n"
        "    schema: schemas/rule.schema.yaml\n"
        "    metadata:\n"
        "      tags: {type: custom, value: [x]}\n"
    )
    config.write_text(text, encoding="utf-8")
    # 実行
    code = main(["migrate", "--source", str(config), "--allow-destructive"])
    # 検証
    error = capsys.readouterr().err
    assert code == 4
    assert "documents[1].type" in error
    assert "documents[1].defaults" in error
    assert "documents[2].metadata.tags" in error
    assert "/project-index:setup" in error
    assert config.read_text(encoding="utf-8") == text
    assert _backups(folder) == []


def test_error_when_config_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """version の無い設定は移し替えずに終了コード 2 で止める（異常系）。"""
    # 準備
    settings = tmp_path / "settings.yaml"
    text = "clone: /x\n"
    settings.write_text(text, encoding="utf-8")
    monkeypatch.setenv("PROJECT_INDEX_CONFIG", str(settings))
    # 実行
    code = main(["migrate"])
    # 検証
    assert code == 2
    assert "version" in capsys.readouterr().err
    assert settings.read_text(encoding="utf-8") == text
    assert _backups(tmp_path) == []


@pytest.mark.usefixtures("versions_2")
def test_error_when_step_fails(
    settings_file: Path,
    write_steps: Callable[..., None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """当てた結果が新しいスキーマに違反すると、書き換えず終了コード 4 で止める（異常系）。"""
    # 準備
    write_steps(
        "settings",
        "2",
        [{"op": "rename", "path": "clone", "to": "clone_old", "description": "必須のキーを改名"}],
    )
    # 実行
    code = main(["migrate"])
    # 検証
    error = capsys.readouterr().err
    assert code == 4
    assert "clone" in error
    assert settings_file.read_text(encoding="utf-8") == SETTINGS_V1


@pytest.mark.usefixtures("versions_2")
def test_error_when_destructive_step_blocked(
    settings_file: Path,
    write_steps: Callable[..., None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """破壊的な手順は `--allow-destructive` なしでは触らず終了コード 5 で止める（異常系）。"""
    # 準備
    write_steps("settings", "2", [{"op": "delete", "path": "log_dir", "description": "削除"}])
    # 実行
    blocked = main(["migrate"])
    error = capsys.readouterr().err
    unchanged = settings_file.read_text(encoding="utf-8")
    backups = _backups(settings_file.parent)
    allowed = main(["migrate", "--allow-destructive"])
    # 検証
    assert blocked == 5
    assert "削除" in error
    assert unchanged == SETTINGS_V1
    assert backups == []
    assert allowed == 0
    assert load_yaml(settings_file.read_text(encoding="utf-8")) == {"version": "2", "clone": "/x"}


def test_error_when_config_newer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """project-index より新しい version の設定は移し替えず終了コード 6 で止める（異常系）。"""
    # 準備
    settings = tmp_path / "settings.yaml"
    text = 'version: "99"\nclone: /x\n'
    settings.write_text(text, encoding="utf-8")
    monkeypatch.setenv("PROJECT_INDEX_CONFIG", str(settings))
    # 実行
    code = main(["migrate"])
    # 検証
    assert code == 6
    assert "project-index を更新してください" in capsys.readouterr().err
    assert settings.read_text(encoding="utf-8") == text

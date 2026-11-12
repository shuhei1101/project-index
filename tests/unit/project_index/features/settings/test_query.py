from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import logging

import pytest

from project_index.features.settings.query import (
    UNKNOWN_KEY_REASON,
    config_path,
    listen_port,
    load_terminal_config,
    log_unknown_keys,
    state_dir_path,
    unknown_key_warnings,
    unknown_top_level_keys,
    validate_terminal_config,
    xdg_base_dir,
)
from project_index.features.settings.types import TerminalConfig, TerminalConfigInvalidError

if TYPE_CHECKING:
    from collections.abc import Callable


def test_config_path() -> None:
    """環境変数の値（正常系）。"""
    # 準備
    env = {"PROJECT_INDEX_CONFIG": "/tmp/x/settings.yaml"}
    # 実行
    result = config_path(env)
    # 検証
    assert result == Path("/tmp/x/settings.yaml")


def test_config_path_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """環境変数が無い（正常系）。"""
    # 準備
    monkeypatch.setenv("HOME", "/home/u")
    env = {"HOME": "/home/u"}
    # 実行
    result = config_path(env)
    # 検証
    assert result == Path("/home/u/.config/project-index/settings.yaml")


def test_config_path_when_xdg_config_home_set() -> None:
    """XDG_CONFIG_HOME の下（正常系）。"""
    # 準備
    env = {"XDG_CONFIG_HOME": "/tmp/c"}
    # 実行
    result = config_path(env)
    # 検証
    assert result == Path("/tmp/c/project-index/settings.yaml")


def test_xdg_base_dir() -> None:
    """絶対パスの値（正常系）。"""
    # 準備
    env = {"XDG_STATE_HOME": "/tmp/s"}
    # 実行
    result = xdg_base_dir(env, "XDG_STATE_HOME", "~/.local/state")
    # 検証
    assert result == Path("/tmp/s")


@pytest.mark.parametrize("env", [{}, {"XDG_STATE_HOME": ""}, {"XDG_STATE_HOME": "rel"}])
def test_xdg_base_dir_when_unset_or_relative(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """未設定・空の文字列・相対パスは既定（正常系）。"""
    # 準備
    monkeypatch.setenv("HOME", "/home/u")
    # 実行
    result = xdg_base_dir(env, "XDG_STATE_HOME", "~/.local/state")
    # 検証
    assert result == Path("/home/u/.local/state")


def test_state_dir_path() -> None:
    """環境変数が端末の設定より優先（正常系）。"""
    # 準備
    env = {"PROJECT_INDEX_STATE_DIR": "/tmp/b", "XDG_STATE_HOME": "/tmp/c"}
    # 実行
    result = state_dir_path("/tmp/a", env)
    # 検証
    assert result == Path("/tmp/b")


def test_state_dir_path_when_config_value() -> None:
    """端末の設定の値（正常系）。"""
    # 準備
    env = {"XDG_STATE_HOME": "/tmp/c"}
    # 実行
    result = state_dir_path("/tmp/a", env)
    # 検証
    assert result == Path("/tmp/a")


def test_state_dir_path_when_xdg_state_home_set() -> None:
    """XDG_STATE_HOME の下（正常系）。"""
    # 準備
    env = {"XDG_STATE_HOME": "/tmp/c"}
    # 実行
    result = state_dir_path(None, env)
    # 検証
    assert result == Path("/tmp/c/project-index")


def test_state_dir_path_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """どれも無い（正常系）。"""
    # 準備
    monkeypatch.setenv("HOME", "/home/u")
    # 実行
    result = state_dir_path(None, {})
    # 検証
    assert result == Path("/home/u/.local/state/project-index")


def test_load_terminal_config(tmp_path: Path) -> None:
    """既定値を埋める（正常系）。"""
    # 準備
    path = tmp_path / "settings.yaml"
    path.write_text(
        'version: "1"\nclone: /tmp/clone\nsources:\n  - config: /tmp/a/project-index.yaml\n',
        encoding="utf-8",
    )
    # 実行
    result = load_terminal_config(path)
    # 検証
    assert result.port == 8786
    assert result.bind == "127.0.0.1"
    assert result.sources[0].config == ["/tmp/a/project-index.yaml"]
    assert result.log_dir == result.state_dir / "logs"


def test_load_terminal_config_when_state_dir_env_set(tmp_path: Path) -> None:
    """状態の置き場を環境変数で決める（正常系）。"""
    # 準備
    path = tmp_path / "settings.yaml"
    path.write_text(
        'version: "1"\nclone: /tmp/clone\nstate_dir: /tmp/a\n',
        encoding="utf-8",
    )
    env = {"PROJECT_INDEX_STATE_DIR": "/tmp/b"}
    # 実行
    result = load_terminal_config(path, env=env)
    # 検証
    assert result.state_dir == Path("/tmp/b")
    assert result.log_dir == Path("/tmp/b/logs")


def test_load_terminal_config_when_missing(tmp_path: Path) -> None:
    """ファイルが無い（異常系）。"""
    # 準備
    path = tmp_path / "none.yaml"
    # 実行・検証
    with pytest.raises(TerminalConfigInvalidError) as exc_info:
        load_terminal_config(path)
    assert str(path) in exc_info.value.message


def test_load_terminal_config_when_yaml_broken(tmp_path: Path) -> None:
    """YAML として読めない（異常系）。"""
    # 準備
    path = tmp_path / "settings.yaml"
    path.write_text("sources: [\n", encoding="utf-8")
    # 実行・検証
    with pytest.raises(TerminalConfigInvalidError) as exc_info:
        load_terminal_config(path)
    assert len(exc_info.value.violations) == 1
    assert exc_info.value.violations[0].rule.count(":") >= 1


def test_load_terminal_config_when_schema_invalid(tmp_path: Path) -> None:
    """違反を全て集める（異常系）。"""
    # 準備
    path = tmp_path / "settings.yaml"
    path.write_text(
        'version: "1"\nclone: /tmp/clone\nport: abc\nsources:\n  - id: a\n',
        encoding="utf-8",
    )
    # 実行・検証
    with pytest.raises(TerminalConfigInvalidError) as exc_info:
        load_terminal_config(path)
    assert sorted(v.path for v in exc_info.value.violations) == ["port", "sources[0].config"]


def _valid_settings() -> dict[str, object]:
    """必須のキーだけを持つ端末の設定の値を返す。"""
    return {
        "version": "1",
        "clone": "/tmp/clone",
        "sources": [{"config": "/tmp/a/project-index.yaml"}],
    }


def test_validate_terminal_config() -> None:
    """違反が無い（正常系）。"""
    # 準備
    value = _valid_settings()
    # 実行
    result = validate_terminal_config(value)
    # 検証
    assert result == []


def test_validate_terminal_config_when_duplicate_id() -> None:
    """行の ID が重なる（正常系）。"""
    # 準備
    value = _valid_settings()
    value["sources"] = [
        {"id": "a", "config": "/tmp/a/project-index.yaml"},
        {"id": "a", "config": "/tmp/b/project-index.yaml"},
    ]
    # 実行
    result = validate_terminal_config(value)
    # 検証
    assert [v.path for v in result] == ["sources[1].id"]
    assert [v.rule for v in result] == ["a は既に使用されています"]


def test_validate_terminal_config_when_empty_glob() -> None:
    """空の glob（正常系）。"""
    # 準備
    value = _valid_settings()
    value["sources"] = [{"config": "/tmp/a/project-index.yaml", "scope": {"read": [""]}}]
    # 実行
    result = validate_terminal_config(value)
    # 検証
    assert [v.path for v in result] == ["sources[0].scope.read[0]"]
    assert [v.rule for v in result] == ["空の文字列は記載できません"]


def test_validate_terminal_config_when_newer_version() -> None:
    """新しいバージョンの設定（正常系）。"""
    # 準備
    value = _valid_settings()
    value["version"] = "2"
    # 実行
    result = validate_terminal_config(value)
    # 検証
    assert [v.path for v in result] == ["version"]


def test_listen_port(make_terminal_config: Callable[..., TerminalConfig]) -> None:
    """環境変数が優先（正常系）。"""
    # 準備
    config = make_terminal_config(port=9000)
    # 実行
    result = listen_port(config, {"PROJECT_INDEX_PORT": "9100"})
    # 検証
    assert result == 9100


def test_listen_port_when_unset(make_terminal_config: Callable[..., TerminalConfig]) -> None:
    """設定の値（正常系）。"""
    # 準備
    config = make_terminal_config(port=9000)
    # 実行
    result = listen_port(config, {})
    # 検証
    assert result == 9000


def test_listen_port_when_invalid(make_terminal_config: Callable[..., TerminalConfig]) -> None:
    """整数でない（異常系）。"""
    # 準備
    config = make_terminal_config(port=9000)
    # 実行・検証
    with pytest.raises(TerminalConfigInvalidError) as exc_info:
        listen_port(config, {"PROJECT_INDEX_PORT": "abc"})
    assert "PROJECT_INDEX_PORT" in exc_info.value.message


def test_load_terminal_config_when_unknown_top_level_key(tmp_path: Path) -> None:
    """最上位の知らないキーを読み飛ばす（正常系）。"""
    # 準備
    path = tmp_path / "settings.yaml"
    path.write_text(
        'version: "1"\nclone: /tmp/clone\nmindstella:\n  threads: 3\nprot: 9000\n',
        encoding="utf-8",
    )
    # 実行
    result = load_terminal_config(path)
    # 検証
    assert result.unknown_keys == ["mindstella", "prot"]
    assert result.port == 8786


def test_load_terminal_config_when_unknown_row_key(tmp_path: Path) -> None:
    """行の知らないキーは今どおり違反（異常系）。"""
    # 準備
    path = tmp_path / "settings.yaml"
    path.write_text(
        'version: "1"\nclone: /tmp/clone\nsources:\n'
        "  - config: /tmp/a/project-index.yaml\n    enable: false\n",
        encoding="utf-8",
    )
    # 実行・検証
    with pytest.raises(TerminalConfigInvalidError) as exc_info:
        load_terminal_config(path)
    assert [v.path for v in exc_info.value.violations] == ["sources[0].enable"]


def test_validate_terminal_config_when_unknown_top_level_key() -> None:
    """最上位の知らないキーは違反にしない（正常系）。"""
    # 準備
    value = _valid_settings()
    value["mindstella"] = {"threads": 3}
    # 実行
    result = validate_terminal_config(value)
    # 検証
    assert result == []


def test_unknown_top_level_keys() -> None:
    """知らないキーをファイルの順に返す（正常系）。"""
    # 準備
    value = {"version": "1", "mindstella": {"threads": 3}, "clone": "/c", "prot": 9000}
    # 実行
    result = unknown_top_level_keys(value)
    # 検証
    assert result == ["mindstella", "prot"]


def test_unknown_top_level_keys_when_none() -> None:
    """知らないキーが無い（正常系）。"""
    # 準備
    value = {"version": "1", "clone": "/c", "sources": []}
    # 実行
    result = unknown_top_level_keys(value)
    # 検証
    assert result == []


def test_unknown_key_warnings(make_terminal_config: Callable[..., TerminalConfig]) -> None:
    """キーごとの警告（正常系）。"""
    # 準備
    config = make_terminal_config(unknown_keys=["mindstella"])
    empty = make_terminal_config()
    # 実行
    result = unknown_key_warnings(config)
    # 検証
    assert [(w.path, w.reason) for w in result] == [("mindstella", UNKNOWN_KEY_REASON)]
    assert unknown_key_warnings(empty) == []


def test_log_unknown_keys(
    make_terminal_config: Callable[..., TerminalConfig], caplog: pytest.LogCaptureFixture
) -> None:
    """知らないキーを警告のログに書く（正常系）。"""
    # 準備
    config = make_terminal_config(unknown_keys=["mindstella", "prot"])
    empty = make_terminal_config()
    caplog.set_level(logging.WARNING)
    # 実行
    log_unknown_keys(config)
    log_unknown_keys(empty)
    # 検証
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert str(config.file) in warnings[0].getMessage()
    assert "mindstella, prot" in warnings[0].getMessage()


def test_listen_port_when_unknown_key_like_port(tmp_path: Path) -> None:
    """打ち間違いのキーの値を使わない（正常系）。"""
    # 準備
    path = tmp_path / "settings.yaml"
    path.write_text('version: "1"\nclone: /tmp/clone\nprot: 9000\n', encoding="utf-8")
    config = load_terminal_config(path)
    # 実行
    result = listen_port(config, {})
    # 検証
    assert result == 8786

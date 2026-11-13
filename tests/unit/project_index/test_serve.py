from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import socket
import sys
from contextlib import closing, contextmanager
from typing import TYPE_CHECKING, Any

import pytest
import uvicorn

from project_index import main as main_module
from project_index.features.access.types import Target
from project_index.features.convert.service import ConvertService
from project_index.features.describe.source_checks import SourceChecks
from project_index.features.documents.store import DocumentStore
from project_index.features.history.snapshot import SnapshotStore
from project_index.features.sources.registry import SourceRegistry
from project_index.features.validation.service import DocumentChecker
from project_index.main import (
    PortInUseError,
    build_handlers,
    check_port,
    reload_changed_sources,
    reload_sources,
    run_migrate,
    run_serve,
)
from project_index.shared.yaml_io import load_yaml as load_yaml_value

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Generator
    from pathlib import Path

    from project_index.features.settings.types import SourceEntry, TerminalConfig
    from project_index.features.sources.types import ServedSource, SourceStatus


def load_yaml(text: str) -> Any:
    """形の分かっている YAML の文字列を読む。"""
    return load_yaml_value(text)


def _free_port() -> int:
    """OS が払い出して閉じたポートの番号を返す。"""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _listening() -> Generator[int]:
    """テストが `listen` しているポートの番号を渡す。"""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        yield int(sock.getsockname()[1])


@pytest.fixture
def serve_settings(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    sample_files: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """配信できる配信元 1 つの端末の設定を `PROJECT_INDEX_CONFIG` に入れ、その場所を返す。"""
    write_files(tmp_path / "ws", sample_files)
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        f'version: "1"\nclone: {tmp_path}\nstate_dir: {tmp_path / "state"}\n'
        f"sources:\n  - config: {tmp_path / 'ws' / 'project-index.yaml'}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJECT_INDEX_CONFIG", str(settings))
    return settings


def test_run_serve(
    serve_settings: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """待ち受けて配信元を出す（正常系）。"""
    # 準備
    port = _free_port()
    monkeypatch.setenv("PROJECT_INDEX_PORT", str(port))
    configs: list[dict[str, Any]] = []
    real_config = uvicorn.Config

    def recording_config(*args: Any, **kwargs: Any) -> uvicorn.Config:
        configs.append(kwargs)
        return real_config(*args, **kwargs)

    def fake_run(self: uvicorn.Server, *args: Any, **kwargs: Any) -> None:
        self.started = True

    threads: list[threading.Thread] = []
    real_start_loading = main_module.start_loading

    def recording_start_loading(handlers: Any) -> threading.Thread:
        thread = real_start_loading(handlers)
        threads.append(thread)
        return thread

    monkeypatch.setattr(uvicorn, "Config", recording_config)
    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    monkeypatch.setattr(main_module, "start_loading", recording_start_loading)
    # 実行
    code = run_serve(argparse.Namespace())
    threads[0].join(timeout=30)
    # 検証
    lines = capsys.readouterr().out.splitlines()
    assert code == 0
    assert lines.index(f"http://127.0.0.1:{port}/") < lines.index("sample")
    assert configs[0]["host"] == "127.0.0.1"


def test_run_serve_when_config_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """端末の設定が違反する（異常系）。"""
    # 準備
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        'version: "1"\nclone: /tmp/clone\nport: abc\nsources:\n  - id: a\n', encoding="utf-8"
    )
    monkeypatch.setenv("PROJECT_INDEX_CONFIG", str(settings))
    # 実行
    code = run_serve(argparse.Namespace())
    # 検証
    error = capsys.readouterr().err
    assert code == 2
    assert "sources[0].config" in error
    assert "port" in error


def test_run_serve_when_port_in_use(
    serve_settings: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ポートが使用中（異常系）。"""
    # 準備・実行
    with _listening() as port:
        monkeypatch.setenv("PROJECT_INDEX_PORT", str(port))
        code = run_serve(argparse.Namespace())
    # 検証
    error = capsys.readouterr().err
    assert code == 3
    assert str(port) in error
    assert "PROJECT_INDEX_PORT" in error


def test_run_serve_when_prompt_invalid(
    tmp_path: Path,
    serve_settings: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """プロンプトの YAML が違反する（異常系）。"""
    from project_index.features.prompt_doc.runtime import DEFAULT_PROMPTS_DIR

    # 準備
    prompts = tmp_path / "prompts"
    shutil.copytree(DEFAULT_PROMPTS_DIR, prompts)
    broken = prompts / "mcp/docs/tools/search-docs.yaml"
    value = load_yaml(broken.read_text(encoding="utf-8"))
    del value["kind"]
    broken.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("PROJECT_INDEX_PROMPTS_DIR", str(prompts))
    monkeypatch.setenv("PROJECT_INDEX_PORT", str(_free_port()))
    runs: list[uvicorn.Server] = []

    def fake_run(self: uvicorn.Server, *args: Any, **kwargs: Any) -> None:
        runs.append(self)

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    # 実行
    code = run_serve(argparse.Namespace())
    # 検証
    error = capsys.readouterr().err
    assert code == 4
    assert str(broken) in error
    assert "kind" in error
    assert runs == []


def test_run_serve_when_restart(serve_settings: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """再起動の要求で同じプロセスを置き換える（正常系）。"""
    # 準備
    monkeypatch.setenv("PROJECT_INDEX_PORT", str(_free_port()))
    captured: dict[str, Any] = {}
    real_build_handlers = main_module.build_handlers

    def spy_build_handlers(terminal: TerminalConfig) -> Any:
        captured["handlers"] = real_build_handlers(terminal)
        return captured["handlers"]

    configs: list[dict[str, Any]] = []
    real_config = uvicorn.Config

    def recording_config(*args: Any, **kwargs: Any) -> uvicorn.Config:
        configs.append(kwargs)
        return real_config(*args, **kwargs)

    def fake_run(self: uvicorn.Server, *args: Any, **kwargs: Any) -> None:
        self.started = True
        captured["handlers"].restart.request()

    executed: list[tuple[str, list[str]]] = []

    def fake_execv(path: str, argv: list[str]) -> None:
        executed.append((path, argv))

    monkeypatch.setattr(main_module, "build_handlers", spy_build_handlers)
    monkeypatch.setattr(uvicorn, "Config", recording_config)
    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    monkeypatch.setattr(os, "execv", fake_execv)
    # 実行
    run_serve(argparse.Namespace())
    # 検証
    assert executed == [(sys.executable, [sys.executable, "-m", "project_index", "serve"])]
    assert configs[0]["timeout_graceful_shutdown"] == 30 * 1.5


def test_check_port() -> None:
    """空いているポート（正常系）。"""
    # 準備
    port = _free_port()
    # 実行・検証
    check_port("127.0.0.1", port)


def test_check_port_when_time_wait() -> None:
    """閉じたばかりの接続が残るポート（正常系）。"""
    # 準備
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = int(server.getsockname()[1])
        with closing(socket.create_connection(("127.0.0.1", port))):
            connection, _ = server.accept()
            # サーバー側から先に閉じて、サーバー側のポートに TIME_WAIT を残す
            connection.close()
    # 実行・検証
    check_port("127.0.0.1", port)


def test_check_port_when_in_use() -> None:
    """使用中のポート（異常系）。"""
    # 準備・実行・検証
    with _listening() as port, pytest.raises(PortInUseError) as exc_info:
        check_port("127.0.0.1", port)
    assert exc_info.value.port == port


def test_build_handlers(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    sample_files: dict[str, str],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """部品を作り配信元は読まない（正常系）。"""
    # 準備
    write_files(tmp_path / "ok", sample_files)
    write_files(
        tmp_path / "broken",
        {
            "project-index.yaml": (
                "name: broken\ndocuments:\n  - id: rules\n    schema: schemas/rule.schema.yaml\n"
            )
        },
    )
    state_dir = tmp_path / "new-state"
    terminal = make_terminal_config(
        state_dir=state_dir,
        sources=[
            make_entry(str(tmp_path / "ok" / "project-index.yaml")),
            make_entry(str(tmp_path / "broken" / "project-index.yaml")),
        ],
    )
    # 実行
    handlers = build_handlers(terminal)
    loading = handlers.registry.loading
    statuses_before = handlers.registry.statuses()
    handlers.reload_sources(terminal)
    # 検証
    assert state_dir.is_dir()
    assert loading is True
    assert statuses_before == []
    assert len(handlers.registry.served()) == 1
    assert len(handlers.registry.statuses()) == 2
    assert "session-context" not in handlers.prompts.prompts
    assert "mcp/docs/instructions" in handlers.prompts.prompts


def test_build_handlers_when_prompt_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """プロンプトの YAML が違反すると部品を作らない（異常系）。"""
    from project_index.features.prompt_doc.types import PromptInvalidError

    # 準備
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    monkeypatch.setenv("PROJECT_INDEX_PROMPTS_DIR", str(prompts))
    state_dir = tmp_path / "new-state"
    terminal = make_terminal_config(state_dir=state_dir)
    # 実行
    with pytest.raises(PromptInvalidError):
        build_handlers(terminal)
    # 検証
    assert not state_dir.exists()


SYNC_SCHEMA = "title: rule\ntype: object\nproperties:\n  id: {type: string}\nrequired: [id]\n"
SYNC_RULES_CONFIG = (
    "name: {name}\n"
    "documents:\n"
    "  - id: rules\n"
    "    paths: [docs/rule/*.yaml]\n"
    "    schema: schemas/rule.schema.yaml\n"
    "    metadata:\n"
    "      name: title\n"
)
SYNC_SRC_CONFIG = (
    "  - id: src\n"
    "    paths: [src/files.yaml]\n"
    "    schema: schemas/rule.schema.yaml\n"
    "    records: files\n"
    "    body_file: path\n"
)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """記録した警告のログの本文を返す。"""
    return [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]


def test_build_handlers_when_out_of_sync(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """初回の読み込みでもずれを警告のログに書く（正常系）。"""
    # 準備
    write_files(
        tmp_path / "ws",
        {
            "project-index.yaml": SYNC_RULES_CONFIG.format(name="sample"),
            "schemas/rule.schema.yaml": SYNC_SCHEMA,
            "docs/rule/doc-1.yaml": "id: doc-1\ntitle: 文書 1\n",
            "docs/rule/doc-2.yaml": "id: doc-2\n",
        },
    )
    terminal = make_terminal_config(
        sources=[make_entry(str(tmp_path / "ws" / "project-index.yaml"))]
    )
    # 実行
    handlers = build_handlers(terminal)
    with caplog.at_level(logging.WARNING):
        handlers.reload_sources(terminal)
    # 検証
    warnings = [message for message in _warnings(caplog) if "sample" in message]
    assert len(warnings) == 1
    assert "name（title）" in warnings[0]
    assert len(handlers.registry.served()) == 1


def test_build_handlers_when_default_ref_moved(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """default_ref が進んだ後は新しい設定で文書を読む（正常系）。"""
    # 準備
    config = (
        "name: a\n"
        "documents:\n"
        "  - id: rules\n"
        "    paths: [docs/rule/*.yaml]\n"
        "    schema: schemas/rule.schema.yaml\n"
    )
    root = git_repo(
        {
            "project-index.yaml": config,
            "schemas/rule.schema.yaml": SYNC_SCHEMA,
            "docs/rule/doc-1.yaml": "id: doc-1\nname: 文書 1\ntitle: タイトル\n",
        }
    )
    terminal = make_terminal_config(
        sources=[make_entry(str(root / "project-index.yaml"), source_id="a")]
    )
    handlers = build_handlers(terminal)
    handlers.reload_sources(terminal)
    before = handlers.registry.get("a")
    handlers.store.load(Target(before, before.root, None, None, "read"))
    commit_all(root, {"project-index.yaml": config + "    metadata:\n      name: title\n"})
    # 実行
    source = handlers.registry.get("a")
    documents = handlers.store.load(Target(source, source.root, None, None, "read")).documents
    # 検証
    assert [document.metadata["name"] for document in documents] == ["タイトル"]


class _Recorder:
    """呼ばれた順を共有の記録へ残す部品の偽物。"""

    def __init__(
        self, name: str, calls: list[str], statuses: list[SourceStatus] | None = None
    ) -> None:
        self._name = name
        self._calls = calls
        self._statuses = statuses or []

    def reload(self, terminal: TerminalConfig) -> list[SourceStatus]:
        self._calls.append(f"{self._name}.reload")
        return self._statuses

    def served(self) -> list[object]:
        return []

    def clear(self) -> None:
        self._calls.append(f"{self._name}.clear")


def test_reload_sources(
    make_terminal_config: Callable[..., TerminalConfig],
    make_status: Callable[..., SourceStatus],
) -> None:
    """読み直してからキャッシュを捨てる（正常系）。"""
    # 準備
    calls: list[str] = []
    statuses = [make_status("sample", 0)]
    registry = _Recorder("registry", calls, statuses)
    # 実行
    result = reload_sources(
        make_terminal_config(),
        registry=registry,  # type: ignore[arg-type]
        store=_Recorder("store", calls),  # type: ignore[arg-type]
        checker=_Recorder("checker", calls),  # type: ignore[arg-type]
        converter=_Recorder("converter", calls),  # type: ignore[arg-type]
        checks=SourceChecks(),
    )
    # 検証
    assert calls[0] == "registry.reload"
    assert sorted(calls[1:]) == ["checker.clear", "converter.clear", "store.clear"]
    assert result == statuses


def test_reload_sources_when_out_of_sync(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """メタデータのずれを警告のログに書く（正常系）。"""
    # 準備
    write_files(
        tmp_path / "sample",
        {
            "project-index.yaml": SYNC_RULES_CONFIG.format(name="sample") + SYNC_SRC_CONFIG,
            "schemas/rule.schema.yaml": SYNC_SCHEMA,
            "docs/rule/doc-1.yaml": "id: doc-1\ntitle: 文書 1\n",
            "docs/rule/doc-2.yaml": "id: doc-2\n",
            "src/files.yaml": (
                "files:\n  - path: a.py\n    related:\n      - to: src/none.py\n  - path: c.py\n"
            ),
            "src/a.py": "a = 1\n",
            "src/d.py": "d = 4\n",
            "src/sub/e.py": "e = 5\n",
        },
    )
    write_files(
        tmp_path / "clean",
        {
            "project-index.yaml": SYNC_RULES_CONFIG.format(name="clean"),
            "schemas/rule.schema.yaml": SYNC_SCHEMA,
            "docs/rule/doc-1.yaml": "id: doc-1\ntitle: 文書 1\n",
        },
    )
    terminal = make_terminal_config(
        sources=[
            make_entry(str(tmp_path / "sample" / "project-index.yaml")),
            make_entry(str(tmp_path / "clean" / "project-index.yaml")),
        ]
    )
    snapshots = SnapshotStore(tmp_path / "snapshots")
    store = DocumentStore(snapshots)
    # 実行
    with caplog.at_level(logging.WARNING):
        statuses = reload_sources(
            terminal,
            registry=SourceRegistry(),
            store=store,
            checker=DocumentChecker(store, timeout_sec=10),
            converter=ConvertService(tmp_path / "converted", store, 10),
            checks=SourceChecks(),
        )
    # 検証
    warnings = _warnings(caplog)
    sample = [message for message in warnings if "sample" in message]
    assert len(sample) == 4
    assert any("name（title）" in message and "1" in message for message in sample)
    assert any(
        "src: src/d.py" in message and "src: src/sub/e.py" in message and "2" in message
        for message in sample
    )
    assert any("c.py" in message and "1" in message for message in sample)
    assert any("src: src/a.py: src/none.py" in message and "1" in message for message in sample)
    assert [message for message in warnings if "clean" in message] == []
    assert [status.status for status in statuses] == ["serving", "serving"]


def _write_settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> Path:
    """端末の設定を書いて `PROJECT_INDEX_CONFIG` に入れ、そのパスを返す。"""
    path = tmp_path / "settings.yaml"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("PROJECT_INDEX_CONFIG", str(path))
    return path


def _migrate_args(**overrides: Any) -> argparse.Namespace:
    """`migrate` の解析結果を作る。"""
    values: dict[str, Any] = {
        "plan": False,
        "record": False,
        "source": None,
        "allow_destructive": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


SETTINGS_V1 = 'version: "1"\nclone: /x\nlog_dir: /logs\n'


@pytest.mark.usefixtures("settings_version_2")
def test_run_migrate_when_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    write_steps: Callable[..., None],
) -> None:
    """当てる手順を表示するだけで書き換えない（正常系）。"""
    # 準備
    settings = _write_settings_file(tmp_path, monkeypatch, SETTINGS_V1)
    write_steps(
        "settings",
        "2",
        [
            {"op": "rename", "path": "log_dir", "to": "state_dir", "description": "改名"},
            {"op": "delete", "path": "legacy", "description": "削除"},
        ],
    )
    # 実行
    code = run_migrate(_migrate_args(plan=True))
    # 検証
    assert code == 0
    assert capsys.readouterr().out.splitlines() == ["2: 改名", "2: 削除 [destructive]"]
    assert settings.read_text(encoding="utf-8") == SETTINGS_V1


@pytest.mark.usefixtures("settings_version_2")
def test_run_migrate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    write_steps: Callable[..., None],
) -> None:
    """手順を当ててバックアップを取る（正常系）。"""
    # 準備
    settings = _write_settings_file(tmp_path, monkeypatch, SETTINGS_V1)
    write_steps(
        "settings",
        "2",
        [{"op": "rename", "path": "log_dir", "to": "state_dir", "description": "改名"}],
    )
    # 実行
    code = run_migrate(_migrate_args())
    # 検証
    assert code == 0
    assert load_yaml(settings.read_text(encoding="utf-8")) == {
        "version": "2",
        "clone": "/x",
        "state_dir": "/logs",
    }
    assert "settings.yaml.bak-" in capsys.readouterr().out


def test_run_migrate_when_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """同じバージョンなら何もしない（正常系）。"""
    # 準備
    settings = _write_settings_file(tmp_path, monkeypatch, SETTINGS_V1)
    # 実行
    code = run_migrate(_migrate_args())
    # 検証
    assert code == 0
    assert "移し替えは要りません" in capsys.readouterr().out
    assert list(settings.parent.glob("*.bak-*")) == []


@pytest.mark.usefixtures("settings_version_2")
def test_run_migrate_when_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_steps: Callable[..., None]
) -> None:
    """`--record` は version だけを書き換える（正常系）。"""
    # 準備
    settings = _write_settings_file(tmp_path, monkeypatch, SETTINGS_V1)
    write_steps(
        "settings",
        "2",
        [{"op": "rename", "path": "log_dir", "to": "state_dir", "description": "改名"}],
    )
    # 実行
    code = run_migrate(_migrate_args(record=True))
    # 検証
    assert code == 0
    assert load_yaml(settings.read_text(encoding="utf-8")) == {
        "version": "2",
        "clone": "/x",
        "log_dir": "/logs",
    }


@pytest.mark.usefixtures("settings_version_2")
def test_run_migrate_when_destructive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    write_steps: Callable[..., None],
) -> None:
    """破壊的な手順で止める（異常系）。"""
    # 準備
    settings = _write_settings_file(tmp_path, monkeypatch, SETTINGS_V1)
    write_steps("settings", "2", [{"op": "delete", "path": "log_dir", "description": "削除"}])
    # 実行
    code = run_migrate(_migrate_args())
    # 検証
    assert code == 5
    assert "--allow-destructive" in capsys.readouterr().err
    assert settings.read_text(encoding="utf-8") == SETTINGS_V1


def test_run_migrate_when_newer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """新しすぎる設定を書き換えない（異常系）。"""
    # 準備
    text = 'version: "9"\nclone: /x\n'
    settings = _write_settings_file(tmp_path, monkeypatch, text)
    # 実行
    code = run_migrate(_migrate_args())
    # 検証
    assert code == 6
    assert "project-index を更新してください" in capsys.readouterr().err
    assert settings.read_text(encoding="utf-8") == text


def test_run_migrate_when_config_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """対象が無い（異常系）。"""
    # 準備
    missing = tmp_path / "missing" / "project-index.yaml"
    # 実行
    code = run_migrate(_migrate_args(source=str(missing)))
    # 検証
    assert code == 2
    assert str(missing) in capsys.readouterr().err


def _files_args(**overrides: Any) -> argparse.Namespace:
    """`files` の解析結果を作る。"""
    values: dict[str, Any] = {"root": "", "paths": ["src/**"], "exclude": []}
    values.update(overrides)
    return argparse.Namespace(**values)


def test_run_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    write_files: Callable[[Path, dict[str, str]], None],
) -> None:
    """載せるファイルを 1 行ずつ出す（正常系）。"""
    # 準備
    write_files(tmp_path, {"src/a.py": "a = 1\n", "src/uv.lock": "version = 1\n"})
    # 実行
    code = main_module.run_files(_files_args(root=str(tmp_path), paths=["src/**"], exclude=[]))
    # 検証
    assert code == 0
    assert capsys.readouterr().out == "src/a.py\n"


def test_run_files_when_root_not_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """フォルダが無い（異常系）。"""
    # 準備
    missing = tmp_path / "missing"
    # 実行
    code = main_module.run_files(_files_args(root=str(missing)))
    # 検証
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert str(missing) in captured.err


def test_reload_sources_when_alias_and_nav(
    tmp_path: Path,
    make_alias_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """エイリアスのキーと nav の条件の警告（正常系）。"""
    # 準備
    config = make_alias_source_dir(broken=True, none_nav=True)
    terminal = make_terminal_config(sources=[make_entry(str(config))])
    store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
    # 実行
    with caplog.at_level(logging.WARNING):
        statuses = reload_sources(
            terminal,
            registry=SourceRegistry(),
            store=store,
            checker=DocumentChecker(store, timeout_sec=10),
            converter=ConvertService(tmp_path / "converted", store, 10),
            checks=SourceChecks(),
        )
    # 検証
    warnings = [message for message in _warnings(caplog) if "sample" in message]
    alias = [
        message
        for message in warnings
        if "docs/term/broken.yaml" in message and "文字列か文字列の並びではありません" in message
    ]
    nav = [message for message in warnings if "nav.tabs[1].items[0].auto.filter" in message]
    assert len(alias) == 1
    assert "aliases" in alias[0]
    assert len(nav) == 1
    assert "none:" in nav[0]
    assert [status.status for status in statuses] == ["serving"]


def test_start_loading(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    sample_files: dict[str, str],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """裏で配信元を読み ID を出す（正常系）。"""
    # 準備
    write_files(tmp_path / "ws", sample_files)
    terminal = make_terminal_config(
        sources=[make_entry(str(tmp_path / "ws" / "project-index.yaml"))]
    )
    handlers = build_handlers(terminal)
    # 実行
    thread = main_module.start_loading(handlers)
    thread.join(timeout=30)
    # 検証
    assert handlers.registry.loading is False
    assert len(handlers.registry.served()) == 1
    assert handlers.checks.get("sample") is not None
    assert "sample" in capsys.readouterr().out.splitlines()


def test_start_loading_when_failed(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    sample_files: dict[str, str],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """読み込みの例外をログに書いて待ちを解く（異常系）。"""
    # 準備
    write_files(tmp_path / "ws", sample_files)
    terminal = make_terminal_config(
        sources=[make_entry(str(tmp_path / "ws" / "project-index.yaml"))]
    )
    handlers = build_handlers(terminal)

    def failing_refresh(store: DocumentStore, source: Any) -> Any:
        msg = "検査に失敗した"
        raise RuntimeError(msg)

    handlers.checks.refresh = failing_refresh  # type: ignore[method-assign]
    # 実行
    with caplog.at_level(logging.ERROR):
        thread = main_module.start_loading(handlers)
        thread.join(timeout=30)
    # 検証
    assert len([record for record in caplog.records if record.levelno == logging.ERROR]) == 1
    assert handlers.registry.loading is False


def test_check_sources(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """キャッシュを捨てずに検査の結果を持たせる（正常系）。"""
    # 準備
    from project_index.main import check_sources

    write_files(
        tmp_path / "sample",
        {
            "project-index.yaml": SYNC_RULES_CONFIG.format(name="sample") + SYNC_SRC_CONFIG,
            "schemas/rule.schema.yaml": SYNC_SCHEMA,
            "docs/rule/doc-1.yaml": "id: doc-1\ntitle: 文書 1\n",
            "src/files.yaml": "files:\n  - path: a.py\n",
            "src/a.py": "a = 1\n",
            "src/d.py": "d = 4\n",
        },
    )
    terminal = make_terminal_config(
        sources=[make_entry(str(tmp_path / "sample" / "project-index.yaml"))]
    )
    registry = SourceRegistry()
    registry.reload(terminal)
    store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
    cleared: list[bool] = []
    store.clear = lambda: cleared.append(True)  # type: ignore[method-assign]
    checks = SourceChecks()
    # 実行
    check_sources(registry.served(), store=store, checks=checks)
    # 検証
    check = checks.get("sample")
    assert check is not None
    assert len(check.report.unindexed_files) == 1
    assert cleared == []


class _ChangedRegistry:
    """`reload_changed` の前後で配信中の配信元を入れ替える配信元の一覧の偽物。"""

    def __init__(
        self,
        calls: list[str],
        before: list[ServedSource],
        after: list[ServedSource],
        statuses: list[SourceStatus],
    ) -> None:
        self._calls = calls
        self._served = before
        self._after = after
        self._statuses = statuses

    def reload_changed(self, terminal: TerminalConfig) -> list[SourceStatus]:
        self._calls.append("registry.reload_changed")
        self._served = self._after
        return self._statuses

    def served(self) -> list[ServedSource]:
        return self._served


def test_reload_changed_sources(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """変わった行を読み直してから、新しく読んだ配信元だけでキャッシュを捨てる（正常系）。"""
    # 準備
    calls: list[str] = []
    a = make_served_source(id="a")
    b = make_served_source(id="b")
    statuses = [make_status("a", 0), make_status("b", 1)]
    registry = _ChangedRegistry(calls, [a], [a, b], statuses)
    checked: list[list[str]] = []

    def fake_check_sources(sources: list[ServedSource], *, store: object, checks: object) -> None:
        checked.append([source.id for source in sources])

    monkeypatch.setattr(main_module, "check_sources", fake_check_sources)
    # 実行
    result = reload_changed_sources(
        make_terminal_config(),
        registry=registry,  # type: ignore[arg-type]
        store=_Recorder("store", calls),  # type: ignore[arg-type]
        checker=_Recorder("checker", calls),  # type: ignore[arg-type]
        converter=_Recorder("converter", calls),  # type: ignore[arg-type]
        checks=SourceChecks(),
    )
    # 検証
    assert calls[0] == "registry.reload_changed"
    assert sorted(calls[1:]) == ["checker.clear", "converter.clear", "store.clear"]
    assert checked == [["b"]]
    assert result == statuses


def test_build_handlers_when_unknown_key_reloaded(
    make_terminal_config: Callable[..., TerminalConfig],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """読み直しで知らないキーを差し替える（正常系）。"""
    # 準備
    terminal = make_terminal_config()
    handlers = build_handlers(terminal)
    new_terminal = make_terminal_config(unknown_keys=["mindstella"])
    caplog.set_level(logging.WARNING)
    # 実行
    handlers.reload_sources(new_terminal)
    # 検証
    assert handlers.terminal.unknown_keys == ["mindstella"]
    assert any("mindstella" in record.getMessage() for record in caplog.records)


def test_build_handlers_when_unknown_key_reloaded_changed(
    make_terminal_config: Callable[..., TerminalConfig],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """変わった配信元の読み直しでも知らないキーを差し替える（正常系）。"""
    # 準備
    terminal = make_terminal_config(unknown_keys=["old"])
    handlers = build_handlers(terminal)
    new_terminal = make_terminal_config(unknown_keys=["mindstella"])
    caplog.set_level(logging.WARNING)
    # 実行
    handlers.reload_changed(new_terminal)
    # 検証
    assert handlers.terminal.unknown_keys == ["mindstella"]
    assert any("mindstella" in record.getMessage() for record in caplog.records)

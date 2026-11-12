from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from project_index.features.describe import source_checks as source_checks_module
from project_index.features.describe.source_checks import SourceChecks
from project_index.features.documents.types import SyncReport
from project_index.main import Handlers, build_handlers

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest
    from project_index.features.settings.types import SourceEntry, TerminalConfig
    from project_index.features.sources.types import ServedSource


def _sample(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> tuple[Handlers, ServedSource]:
    """管理用の YAML に無いファイルが 1 件ある配信元 sample を読んだ部品と、その配信元を返す。"""
    terminal = make_terminal_config(
        sources=[make_entry(str(make_source_dir("sample", unindexed=1)), source_id="sample")]
    )
    handlers = build_handlers(terminal)
    handlers.reload_sources(terminal)
    return handlers, handlers.registry.get("sample")


def test_source_checks_refresh(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """検査して結果を持つ（正常系）。"""
    # 準備
    handlers, source = _sample(make_source_dir, make_terminal_config, make_entry)
    checks = SourceChecks()
    # 実行
    result = checks.refresh(handlers.store, source)
    # 検証
    held = checks.get("sample")
    assert len(result.report.unindexed_files) == 1
    assert held is not None
    assert len(held.report.unindexed_files) == 1


def test_source_checks_get_when_unchecked() -> None:
    """検査していない配信元（正常系）。"""
    # 準備
    checks = SourceChecks()
    # 実行
    result = checks.get("sample")
    # 検証
    assert result is None


def test_source_checks_refresh_later(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """裏で検査し直す（正常系）。"""
    # 準備
    handlers, source = _sample(make_source_dir, make_terminal_config, make_entry)
    checks = SourceChecks()
    # 実行
    threads = checks.refresh_later(handlers.store, [source])
    for thread in threads:
        thread.join(timeout=30)
    # 検証
    assert checks.get("sample") is not None


def _report(source_id: str, unindexed: int) -> SyncReport:
    """管理用の YAML に無いファイルを `unindexed` 件持つ同期のずれを作る。"""
    return SyncReport(
        source_id=source_id,
        missing_refs=[],
        unindexed_files=[f"src: f{index}.py" for index in range(unindexed)],
        missing_body_files=[],
        unresolved_related=[],
        alias_violations=[],
    )


def _gated_check_sync(
    monkeypatch: pytest.MonkeyPatch, first_gate: threading.Event
) -> tuple[list[int], threading.Event]:
    """呼んだ順に `unindexed` が 1, 2, ... 件の結果を返し、1 回目だけ合図まで止める偽物に差し替える。"""
    calls: list[int] = []
    first_started = threading.Event()
    lock = threading.Lock()

    def fake_check_sync(store: Any, source: Any) -> SyncReport:
        with lock:
            calls.append(len(calls) + 1)
            number = len(calls)
        if number == 1:
            first_started.set()
            first_gate.wait(10)
        return _report(source.id, number)

    monkeypatch.setattr(source_checks_module, "check_sync", fake_check_sync)
    monkeypatch.setattr(source_checks_module, "nav_warnings", lambda store, source: [])
    return calls, first_started


def test_source_checks_refresh_when_older_finished_later(
    monkeypatch: pytest.MonkeyPatch,
    make_served_source: Callable[..., ServedSource],
) -> None:
    """後に始めた検査の結果を、先に始めて後に終わった検査で上書きしない（正常系）。"""
    # 準備
    gate = threading.Event()
    _, first_started = _gated_check_sync(monkeypatch, gate)
    source = make_served_source(id="sample", root=Path("/w/sample"))
    checks = SourceChecks()
    first = threading.Thread(target=checks.refresh, args=(None, source))
    first.start()
    first_started.wait(10)
    # 実行
    checks.refresh(None, source)  # type: ignore[arg-type]
    gate.set()
    first.join(timeout=10)
    # 検証
    held = checks.get("sample")
    assert held is not None
    assert len(held.report.unindexed_files) == 2


def test_source_checks_refresh_later_when_running(
    monkeypatch: pytest.MonkeyPatch,
    make_served_source: Callable[..., ServedSource],
) -> None:
    """裏で検査中に要求されたら、スレッドを増やさず 1 回だけ流し直す（正常系）。"""
    # 準備
    gate = threading.Event()
    calls, first_started = _gated_check_sync(monkeypatch, gate)
    source = make_served_source(id="sample", root=Path("/w/sample"))
    checks = SourceChecks()
    threads = checks.refresh_later(None, [source])  # type: ignore[arg-type]
    first_started.wait(10)
    # 実行
    second = checks.refresh_later(None, [source])  # type: ignore[arg-type]
    third = checks.refresh_later(None, [source])  # type: ignore[arg-type]
    gate.set()
    for thread in threads:
        thread.join(timeout=10)
    # 検証
    held = checks.get("sample")
    assert second == []
    assert third == []
    assert calls == [1, 2]
    assert held is not None
    assert len(held.report.unindexed_files) == 2

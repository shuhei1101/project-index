from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from project_index.features.describe import source_checks as source_checks_module
from project_index.features.describe.source_checks import SourceChecks
from project_index.features.documents.types import SyncReport
from project_index.main import Handlers, build_handlers
from project_index.shared.background import BackgroundGate

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
    monkeypatch.setattr(source_checks_module, "nav_warnings", _no_nav_warnings)
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


def _no_nav_warnings(store: object, source: object) -> list[object]:
    """nav の警告を出さない偽物。"""
    return []


def test_source_checks_checking(
    monkeypatch: pytest.MonkeyPatch,
    make_served_source: Callable[..., ServedSource],
) -> None:
    """裏の検査の間だけ True（正常系）。"""
    # 準備
    gate = threading.Event()
    _, first_started = _gated_check_sync(monkeypatch, gate)
    source = make_served_source(id="sample", root=Path("/w/sample"))
    checks = SourceChecks()
    # 実行
    threads = checks.refresh_later(None, [source])  # type: ignore[arg-type]
    first_started.wait(10)
    checking_before = checks.checking
    gate.set()
    for thread in threads:
        thread.join(timeout=10)
    # 検証
    assert checking_before is True
    assert checks.checking is False


def test_source_checks_forget(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """結果を捨てる（正常系）。"""
    # 準備
    handlers, source = _sample(make_source_dir, make_terminal_config, make_entry)
    checks = SourceChecks()
    checks.refresh(handlers.store, source)
    # 実行
    checks.forget(["sample"])
    # 検証
    assert checks.get("sample") is None


def _recording_check_sync(
    monkeypatch: pytest.MonkeyPatch, gate: BackgroundGate
) -> tuple[list[str], list[int], list[bool]]:
    """呼ばれた配信元の ID・同時に実行中の数・関所の裏の処理のスレッドかを記録する偽物に差し替える。"""
    order: list[str] = []
    running_seen: list[int] = []
    background_seen: list[bool] = []
    running = 0
    lock = threading.Lock()

    def fake_check_sync(store: Any, source: Any) -> SyncReport:
        nonlocal running
        with lock:
            running += 1
            order.append(source.id)
            running_seen.append(running)
            background_seen.append(gate.in_background)
        threading.Event().wait(0.01)
        with lock:
            running -= 1
        return _report(source.id, 0)

    monkeypatch.setattr(source_checks_module, "check_sync", fake_check_sync)
    monkeypatch.setattr(source_checks_module, "nav_warnings", _no_nav_warnings)
    return order, running_seen, background_seen


def test_source_checks_refresh_later_when_many(
    monkeypatch: pytest.MonkeyPatch,
    make_served_source: Callable[..., ServedSource],
) -> None:
    """複数の配信元を 1 本のスレッドで順に検査する（正常系）。"""
    # 準備
    gate = BackgroundGate()
    order, running_seen, background_seen = _recording_check_sync(monkeypatch, gate)
    sources = [
        make_served_source(id="a", root=Path("/w/a")),
        make_served_source(id="b", root=Path("/w/b")),
        make_served_source(id="c", root=Path("/w/c")),
    ]
    checks = SourceChecks(gate=gate)
    # 実行
    threads = checks.refresh_later(None, sources)  # type: ignore[arg-type]
    threads[0].join(timeout=10)
    # 検証
    assert len(threads) == 1
    assert order == ["a", "b", "c"]
    assert max(running_seen) == 1
    assert background_seen == [True, True, True]

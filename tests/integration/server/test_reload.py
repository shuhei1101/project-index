from __future__ import annotations

import dataclasses
import logging
import threading
from typing import TYPE_CHECKING, Any

from project_index.features.describe import source_checks as source_checks_module
from project_index.features.documents.store import check_sync

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

# 止めた検査の合図を待つ上限
CHECK_WAIT_SEC = 30


def test_normal(make_source: Callable[..., Any], make_server: Callable[..., Any]) -> None:
    """端末の設定に追加した配信元の配信を始める（正常系）。"""
    # 準備
    sample = make_source("sample")
    notes = make_source("notes", git=False)
    env = make_server(sample)
    env.rewrite_settings(sample, notes)
    # 実行
    result = env.call_admin("reload", format="json")
    env.wait_background()
    status = env.call_admin("status", format="json")
    # 検証
    found = env.call(
        "search_docs", cwd=str(notes.folder), source="notes", view="ids", format="json"
    )
    described = env.call("describe", cwd=str(sample.folder))
    assert result.data["added"] == ["notes"]
    assert "removed" not in result.data
    assert "not_served" not in result.data
    # 空の値は MCP の結果から落ちる
    assert [(item["id"], item.get("sync")) for item in result.data["sources"]] == [
        ("sample", None),
        ("notes", None),
    ]
    assert status.data["checking"] is False
    assert {item["id"]: item["sync"]["unindexed_files"] for item in status.data["sources"]} == {
        "sample": 0,
        "notes": 0,
    }
    assert {item["id"] for item in found.data["items"]} == {"doc-1", "doc-2"}
    assert not described.is_error


def test_normal_when_source_becomes_invalid(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """配信元の設定を壊して再読み込みすると、その配信元を外して返す（正常系）。"""
    # 準備
    sample = make_source("sample", sample_file_set(), git=False)
    env = make_server(sample)
    (sample.folder / "project-index.yaml").write_text(
        "name: sample\ndocuments:\n  - id: sample\n    schema: schemas/sample.schema.yaml\n",
        encoding="utf-8",
    )
    # 実行
    result = env.call_admin("reload", format="json")
    # 検証
    searched = env.call("search_docs", cwd=str(sample.folder), source="sample")
    not_served = result.data["not_served"]
    assert [item["id"] for item in not_served] == ["sample"]
    assert any("documents[0].paths" in error for error in not_served[0]["errors"])
    assert searched.is_error
    assert searched.text.startswith("SourceNotServedError")


def test_error_when_terminal_config_invalid(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """端末の設定がスキーマに違反すると、配信元の一覧を変えずに断る（異常系）。"""
    # 準備
    sample = make_source("sample")
    env = make_server(sample)
    env.settings_path.write_text(
        env.settings_path.read_text(encoding="utf-8").replace("    config:", "    configs:"),
        encoding="utf-8",
    )
    # 実行
    result = env.call_admin("reload")
    # 検証
    searched = env.call("search_docs", cwd=str(sample.folder), source="sample", view="ids")
    assert result.is_error
    assert "sources[0].config" in result.text
    assert not searched.is_error


def test_normal_when_terminal_config_has_unknown_top_level_key(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """端末の設定の最上位に知らないキーがあっても再読み込みし、キーのパスを警告のログと引数なしの describe の警告に残す（正常系）。"""
    # 準備
    sample = make_source("sample", sample_file_set(), git=False)
    env = make_server(sample)
    env.settings_extra = "mindstella:\n  threads: 3"
    env.rewrite_settings(sample)
    (sample.folder / "project-index.yaml").write_text(
        sample_config_text(description="書き換えた説明"), encoding="utf-8"
    )
    caplog.set_level(logging.WARNING)
    # 実行
    result = env.call_admin("reload", format="json")
    # 検証
    described = env.call("describe", cwd=str(sample.folder), format="json")
    assert not result.is_error
    assert "not_served" not in result.data
    assert [item["description"] for item in described.data["sources"]] == ["書き換えた説明"]
    assert len([w for w in described.data["warnings"] if "mindstella" in w]) == 1
    assert any(
        "mindstella" in record.getMessage() and str(env.settings_path) in record.getMessage()
        for record in caplog.records
    )


def test_normal_when_reloaded_before_checks_finish(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_sync_file_set: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """前の検査を待たずに応答し、前の検査の結果で後の結果を上書きしない（正常系）。"""
    # 準備
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def stale_check(store: Any, source: Any) -> Any:
        calls.append(source.id)
        report = check_sync(store, source)
        # 起動の後の 1 回と 2 回目の再読み込みの検査は本物の結果、1 回目の再読み込みの検査は合図まで止めて 5 件の結果
        if len(calls) != 2:
            return report
        entered.set()
        release.wait(timeout=CHECK_WAIT_SEC)
        return dataclasses.replace(report, unindexed_files=[f"stale-{i}.py" for i in range(5)])

    monkeypatch.setattr(source_checks_module, "check_sync", stale_check)
    env = make_server(make_source("sample", sample_sync_file_set(1), git=False))
    env.wait_background()
    # 実行
    first = env.call_admin("reload", format="json")
    reached = entered.wait(timeout=CHECK_WAIT_SEC)
    second = env.call_admin("reload", format="json")
    answered_while_blocked = not release.is_set()
    release.set()
    env.wait_background()
    status = env.call_admin("status", format="json")
    # 検証
    [source] = status.data["sources"]
    assert not first.is_error
    assert reached
    assert not second.is_error
    assert answered_while_blocked
    assert source["sync"]["unindexed_files"] == 1
    assert len(calls) == 3

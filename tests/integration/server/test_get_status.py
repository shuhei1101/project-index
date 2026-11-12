from __future__ import annotations

import json
import threading
from importlib.metadata import version
from typing import TYPE_CHECKING, Any

from project_index.features.describe import source_checks as source_checks_module
from project_index.features.documents.store import check_sync

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

LOADING_LINE = (
    "配信元: 読み込み中（読み込みが終わっていない配信元を指す文書の MCP の呼び出しは待たされます）"
)
# 検査を止めた合図を待つ上限
CHECK_WAIT_SEC = 30
BROKEN_CONFIG = "name: broken\ndocuments:\n  - id: sample\n    schema: schemas/sample.schema.yaml\n"


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_sync_file_set: Callable[..., dict[str, str]],
) -> None:
    """配信中・配信していない配信元の状態を返す（正常系）。"""
    # 準備
    sample = make_source("sample", sample_sync_file_set(1))
    broken = make_source("broken", {"project-index.yaml": BROKEN_CONFIG})
    env = make_server(sample, broken)
    # 実行
    markdown = env.call_admin("status")
    result = env.call_admin("status", format="json")
    # 検証
    sources = {item["id"]: item for item in result.data["sources"]}
    assert not markdown.is_error
    assert result.data["version"] == version("project-index")
    assert sources["sample"]["status"] == "serving"
    assert sources["sample"]["sync"]["unindexed_files"] == 1
    assert sources["sample"]["sync"]["unresolved_related"] == 0
    assert sources["broken"]["status"] == "not_served"
    assert any("documents[0].paths" in error for error in sources["broken"]["errors"])
    assert result.structured == json.loads(result.text)
    assert "| sample | serving |" in markdown.text


def test_normal_when_loading(
    make_source: Callable[..., Any], make_loading_server: Callable[..., Any]
) -> None:
    """配信元の読み込みを待たずに、読み込み中であることを返す（正常系）。"""
    # 準備
    loading = make_loading_server(make_source("sample"))
    env = loading.env
    # 実行
    before = env.call_admin("status", format="json")
    markdown = env.call_admin("status")
    loading.finish()
    after = env.call_admin("status", format="json")
    # 検証
    assert before.data["loading"] is True
    # 空の値は MCP の結果から落ちる
    assert "sources" not in before.data
    assert LOADING_LINE in markdown.text
    assert after.data["loading"] is False
    assert [(item["id"], item["status"]) for item in after.data["sources"]] == [
        ("sample", "serving")
    ]


def test_normal_when_checking(
    make_source: Callable[..., Any],
    make_loading_server: Callable[..., Any],
    sample_sync_file_set: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """検査が済んでいない配信元は、同期の件数を持たずに返す（正常系）。"""
    # 準備
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def blocked_check(store: Any, source: Any) -> Any:
        calls.append(source.id)
        entered.set()
        release.wait(timeout=CHECK_WAIT_SEC)
        return check_sync(store, source)

    monkeypatch.setattr(source_checks_module, "check_sync", blocked_check)
    loading = make_loading_server(make_source("sample", sample_sync_file_set(1)), blocked=())
    env = loading.env
    # 実行
    reached = entered.wait(timeout=CHECK_WAIT_SEC)
    before = env.call_admin("status", format="json")
    markdown = env.call_admin("status")
    release.set()
    loading.thread.join(timeout=CHECK_WAIT_SEC)
    after = env.call_admin("status", format="json")
    # 検証
    [source_before] = before.data["sources"]
    [source_after] = after.data["sources"]
    assert reached
    assert source_before["status"] == "serving"
    # 空の値は MCP の結果から落ちる
    assert source_before.get("sync") is None
    assert "| sample | serving |" in markdown.text
    assert "検査中" in markdown.text
    assert source_after["sync"]["unindexed_files"] == 1
    assert calls == ["sample"]

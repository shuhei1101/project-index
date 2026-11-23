from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from project_index.features.post_write import route as post_write_route
from project_index.features.seen.types import SessionKey
from project_index.shared.runtime import DOCS_WORKERS, POST_WRITE_WORKERS
from tests.integration.server.conftest import (
    ALIAS_ROWS,
    FILES_ROW,
    TERM_SCHEMA,
    sample_config,
    sample_sync_files,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest
    from fastapi.testclient import TestClient

ENDPOINT = "/_admin/post-write"
CRITERIA = "docs/guide/メタデータを付ける基準.md"
# 止めた処理の合図と応答を待つ上限
WAIT_SEC = 30


def _post(env: Any, body: dict[str, Any]) -> Any:
    """`POST /_admin/post-write` をフックと同じく Origin なしで呼ぶ。"""
    client: TestClient = env.client
    return client.post(ENDPOINT, json=body)


def test_normal(make_source: Callable[..., Any], make_server: Callable[..., Any]) -> None:
    """行があるファイルを初めて渡すと update_row の通知を返し、2 回目は返さない（正常系）。"""
    # 準備
    sample = make_source("sample", sample_sync_files(unindexed=1))
    env = make_server(sample)
    path = str(sample.folder / "src/a.py")
    # 実行
    first = _post(env, {"session_id": "s1", "paths": [path]})
    second = _post(env, {"session_id": "s1", "paths": [path]})
    other = _post(env, {"session_id": "s2", "paths": [path]})
    # 検証
    assert first.status_code == 200
    assert first.json()["notices"] == [
        {"path": path, "source": "sample", "action": "update_row", "files_yaml": "src/files.yaml"}
    ]
    assert "中身と合わなくなったときだけ" in first.json()["additional_context"]
    assert CRITERIA in first.json()["additional_context"]
    assert second.json() == {"notices": [], "additional_context": ""}
    assert len(other.json()["notices"]) == 1


def test_normal_when_no_row(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """管理用の YAML の範囲にあり行の無いファイルは add_row の通知を返す（正常系）。"""
    # 準備
    sample = make_source("sample", sample_sync_files(unindexed=1))
    env = make_server(sample)
    path = str(sample.folder / "src/extra0.py")
    # 実行
    response = _post(env, {"session_id": "s1", "paths": [path]})
    # 検証
    body = response.json()
    assert [notice["action"] for notice in body["notices"]] == ["add_row"]
    assert "行を追加します" in body["additional_context"]
    assert CRITERIA in body["additional_context"]


def test_normal_when_source_has_aliases_and_rule_index(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """alias_type の行と rules.yaml を持つ配信元では、文面にそれぞれ 1 行を足す（正常系）。"""
    # 準備
    files = sample_sync_files(unindexed=1)
    files["project-index.yaml"] = sample_config(FILES_ROW + ALIAS_ROWS, version="3")
    files["schemas/term.schema.yaml"] = TERM_SCHEMA
    files["terms/scope.yaml"] = "id: scope\nname: 作業範囲\ndescription: 触ってよい範囲\n"
    files["rules.yaml"] = "rules: []\n"
    sample = make_source("sample", files)
    env = make_server(sample)
    # 実行
    response = _post(env, {"session_id": "s1", "paths": [str(sample.folder / "src/a.py")]})
    # 検証
    text = response.json()["additional_context"]
    assert "alias_type の行の文書に追加します" in text
    assert "rules.yaml のエントリを修正します" in text


def test_normal_when_path_not_notified(
    tmp_path: Path, make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """通知の対象に該当しないパスは通知せず、通知済みの記録にも追加しない（正常系）。"""
    # 準備
    files = sample_sync_files(unindexed=1)
    files["tmp/x.md"] = "# x\n"
    sample = make_source("sample", files)
    env = make_server(sample)
    outside = tmp_path / "outside.md"
    outside.write_text("# outside\n", encoding="utf-8")
    skipped = [
        str(sample.folder / "src/files.yaml"),
        str(sample.folder / "project-index.yaml"),
        str(sample.folder / "tmp/x.md"),
        str(sample.folder / "docs/doc-1.yaml"),
        str(outside),
    ]
    # 実行
    first = _post(env, {"session_id": "s1", "paths": skipped})
    second = _post(env, {"session_id": "s1", "paths": [str(sample.folder / "src/a.py")]})
    # 検証
    assert first.json() == {"notices": [], "additional_context": ""}
    assert [notice["path"] for notice in second.json()["notices"]] == [
        str(sample.folder / "src/a.py")
    ]


def test_normal_when_loading(
    make_source: Callable[..., Any], make_loading_server: Callable[..., Any]
) -> None:
    """配信元の読み込みを待たずに、通知せずに答える（正常系）。"""
    # 準備
    sample = make_source("sample", sample_sync_files(unindexed=1))
    loading = make_loading_server(sample)
    path = str(sample.folder / "src/a.py")
    # 実行
    response = _post(loading.env, {"session_id": "s1", "paths": [path]})
    # 検証
    assert response.status_code == 200
    assert response.json() == {"notices": [], "additional_context": ""}
    assert loading.env.handlers.registry.loading is True
    assert loading.env.handlers.notified.take_new(SessionKey("s1", ""), [path]) == [path]


def test_error_when_input_invalid(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """paths が空だと 422 を返す（異常系）。"""
    # 準備
    env = make_server(make_source("sample", sample_sync_files(unindexed=1)))
    # 実行
    response = _post(env, {"session_id": "s1", "paths": []})
    # 検証
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert any("paths" in item["path"] for item in response.json()["errors"])


def test_normal_when_docs_slots_full(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """文書の MCP の実行スロットが全て使用中でも、待たずに通知を返却する（正常系）。"""
    # 準備
    sample = make_source("sample", sample_sync_files(unindexed=1))
    env = make_server(sample)
    path = str(sample.folder / "src/a.py")
    release = threading.Event()
    blockers = [
        env.handlers.slots.docs_executor.submit(release.wait, WAIT_SEC) for _ in range(DOCS_WORKERS)
    ]
    # 実行
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_post, env, {"session_id": "s1", "paths": [path]})
        response = future.result(timeout=WAIT_SEC)
        # 合図を出す前に応答したか
        answered_before_release = not release.is_set()
        release.set()
    for blocker in blockers:
        blocker.result(timeout=WAIT_SEC)
    # 検証
    assert answered_before_release
    assert response.status_code == 200
    assert response.json()["notices"] == [
        {"path": path, "source": "sample", "action": "update_row", "files_yaml": "src/files.yaml"}
    ]


def test_normal_when_post_write_slots_full(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """判定の実行スロットが全て使用中なら、待たずに通知せずに応答する（正常系）。"""
    # 準備
    sample = make_source("sample", sample_sync_files(unindexed=1))
    env = make_server(sample)
    path = str(sample.folder / "src/a.py")
    judge = post_write_route.judge_post_write
    entered = threading.Semaphore(0)
    release = threading.Event()

    def blocked_judge(request: Any, **kwargs: Any) -> Any:
        # 実行スロットを埋める要求だけを合図まで止める
        if request.session_id.startswith("busy"):
            entered.release()
            release.wait(timeout=WAIT_SEC)
        return judge(request, **kwargs)

    monkeypatch.setattr(post_write_route, "judge_post_write", blocked_judge)
    # 実行
    with ThreadPoolExecutor(max_workers=POST_WRITE_WORKERS) as pool:
        busy = [
            pool.submit(_post, env, {"session_id": f"busy{index}", "paths": [path]})
            for index in range(POST_WRITE_WORKERS)
        ]
        reached = all(entered.acquire(timeout=WAIT_SEC) for _ in range(POST_WRITE_WORKERS))
        full = _post(env, {"session_id": "s1", "paths": [path]})
        # 合図を出す前に応答したか
        answered_before_release = not release.is_set()
        release.set()
        busy_responses = [future.result(timeout=WAIT_SEC) for future in busy]
    after = _post(env, {"session_id": "s1", "paths": [path]})
    # 検証
    assert reached
    assert answered_before_release
    assert full.status_code == 200
    assert full.json() == {"notices": [], "additional_context": ""}
    assert all(response.status_code == 200 for response in busy_responses)
    assert [notice["action"] for notice in after.json()["notices"]] == ["update_row"]

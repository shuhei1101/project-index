from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from tests.integration.server.conftest import sample_config

if TYPE_CHECKING:
    from collections.abc import Callable

BROKEN_CONFIG = "name: broken\ndocuments:\n  - id: sample\n    schema: schemas/sample.schema.yaml\n"


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """配信元ごとの ID・状態・配信していない理由を返す（正常系）。"""
    # 準備
    sample = make_source("sample")
    broken = make_source("broken", sample_file_set(**{"project-index.yaml": BROKEN_CONFIG}))
    archive = make_source("archive", enabled=False)
    env = make_server(sample, broken, archive)
    # 実行
    response = env.client.get("/sources")
    # 検証
    sources = response.json()["sources"]
    assert response.status_code == 200
    assert [(row["id"], row["status"]) for row in sources] == [
        ("sample", "serving"),
        ("broken", "not_served"),
        ("archive", "disabled"),
    ]
    assert any("documents[0]" in error["path"] for error in sources[1]["errors"])


def test_normal_when_no_source(make_server: Callable[..., Any]) -> None:
    """端末の設定に配信元が無いときは空の一覧を返す（正常系）。"""
    # 準備
    env = make_server()
    # 実行
    response = env.client.get("/sources")
    # 検証
    assert response.status_code == 200
    assert response.json()["sources"] == []


def test_normal_when_include_loading(
    make_source: Callable[..., Any],
    make_loading_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """include_loading=true のとき、読み込みが終わっていない配信元を loading で返す（正常系）。"""
    # 準備
    slow = make_source("slow")
    sample = make_source("sample")
    third = dataclasses.replace(
        make_source(
            "third", sample_file_set(**{"project-index.yaml": sample_config(name="third")})
        ),
        with_id=False,
    )
    loading = make_loading_server(slow, sample, third, blocked=("slow", "third"))
    env = loading.env
    # 実行
    before = env.client.get("/sources?include_loading=true")
    loading.finish()
    after = env.client.get("/sources")
    # 検証
    assert before.status_code == 200
    rows = [(row["id"], row["status"]) for row in before.json()["sources"]]
    assert rows[0] == ("slow", "loading")
    assert rows[2] == ("sources[2]", "loading")
    assert after.status_code == 200
    assert [(row["id"], row["status"]) for row in after.json()["sources"]] == [
        ("slow", "serving"),
        ("sample", "serving"),
        ("third", "serving"),
    ]

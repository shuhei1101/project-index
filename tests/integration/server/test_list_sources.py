from __future__ import annotations

from typing import TYPE_CHECKING, Any

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

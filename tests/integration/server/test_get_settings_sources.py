from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

BROKEN_CONFIG = "name: broken\ndocuments:\n  - id: sample\n    schema: schemas/sample.schema.yaml\n"


def test_normal(make_source: Callable[..., Any], make_server: Callable[..., Any]) -> None:
    """配信元の一覧を配信中で返す（正常系）。"""
    # 準備
    source = make_source("sample")
    env = make_server(source)
    # 実行
    response = env.client.get("/settings/sources")
    env.rewrite_settings()
    empty = env.client.get("/settings/sources")
    # 検証
    body = response.json()
    assert response.status_code == 200
    assert body["settingsPath"] == str(env.settings_path)
    assert [(row["id"], row["status"]) for row in body["sources"]] == [("sample", "serving")]
    assert body["sources"][0]["config"] == [str(source.config[0])]
    assert body["sources"][0]["scope"]["read"] == [str(source.folder)]
    assert empty.status_code == 200
    assert empty.json()["sources"] == []


def test_normal_when_source_not_served(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """配信していない・無効・設定が古い配信元を状態と理由つきで返す（正常系）。"""
    # 準備
    sample = make_source("sample")
    legacy_config = sample_config_text(name="legacy", version="0")
    legacy = make_source("legacy", sample_file_set(**{"project-index.yaml": legacy_config}))
    broken = make_source("broken", {"project-index.yaml": BROKEN_CONFIG})
    archive = make_source("archive", enabled=False)
    env = make_server(sample, legacy, broken, archive)
    # 実行
    response = env.client.get("/settings/sources")
    # 検証
    rows = {row["id"]: row for row in response.json()["sources"]}
    assert response.status_code == 200
    assert rows["sample"]["status"] == "serving"
    assert rows["legacy"]["status"] == "serving"
    assert rows["legacy"]["configVersion"] == {"config": "0", "server": "3"}
    assert rows["broken"]["status"] == "not_served"
    assert any(
        error["path"] == "documents[0].paths" and "必須" in error["reason"]
        for error in rows["broken"]["errors"]
    )
    assert rows["archive"]["status"] == "disabled"


def test_normal_when_pending_reload(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """手で直して読み直していない行を pending_reload で返す（正常系）。"""
    # 準備
    sample = make_source("sample")
    other = make_source("other")
    fresh = make_source("fresh")
    env = make_server(sample, other)
    env.rewrite_settings(other, fresh, sample)
    # 実行
    response = env.client.get("/settings/sources")
    # 検証
    rows = response.json()["sources"]
    assert response.status_code == 200
    assert [(row["id"], row["status"]) for row in rows] == [
        ("other", "serving"),
        ("fresh", "pending_reload"),
        ("sample", "serving"),
    ]


def test_normal_when_outside_read_false(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """端末の設定の outside_read を行の outsideRead で返す（正常系）。"""
    # 準備
    sample = make_source("sample")
    extra = make_source("extra", outside_read=False)
    env = make_server(sample, extra)
    # 実行
    response = env.client.get("/settings/sources")
    # 検証
    assert response.status_code == 200
    assert {row["id"]: row["outsideRead"] for row in response.json()["sources"]} == {
        "sample": True,
        "extra": False,
    }

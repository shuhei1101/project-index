from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from project_index.shared.yaml_io import load_yaml
from tests.integration.server.conftest import sample_config, sample_files

if TYPE_CHECKING:
    from collections.abc import Callable

ORIGIN = {"Origin": "http://127.0.0.1:8786"}
SETTINGS_EXTRA = "# 取り込みの保持日数（コメントは保つ）\nseen_retention_days: 5\n"


def _version(env: Any) -> str:
    """端末の設定の取得の内容のバージョンを返す。"""
    return env.client.get("/settings/sources").json()["version"]


def _append_unnamed_row(env: Any, source: Any) -> None:
    """`id` を省いて配信元を指す行を、端末の設定の末尾に手で書き足す。"""
    with env.settings_path.open("a", encoding="utf-8") as file:
        file.write(f"  - config: [{source.config[0]}]\n")


def test_normal(make_source: Callable[..., Any], make_server: Callable[..., Any]) -> None:
    """指した行の送信したキーだけを変更し、その配信元だけを読み直す（正常系）。"""
    # 準備
    sample = make_source("sample")
    extra = make_source("extra")
    extra = dataclasses.replace(extra, scope_write=[extra.folder])
    env = make_server(sample, extra, settings_extra=SETTINGS_EXTRA)
    before = load_yaml(env.settings_path.read_text(encoding="utf-8"))["sources"]
    served = env.handlers.registry.get("sample")
    version = _version(env)
    # 実行
    response = env.client.patch(
        "/settings/sources/extra",
        json={"expectedVersion": version, "source": {"outside_read": False}},
    )
    # 検証
    text = env.settings_path.read_text(encoding="utf-8")
    rows = load_yaml(text)["sources"]
    body = response.json()
    assert response.status_code == 200
    assert body["version"] != version
    assert ("extra", "serving") in [(row["id"], row["status"]) for row in body["sources"]]
    assert rows[1]["outside_read"] is False
    assert rows[1]["scope"] == before[1]["scope"]
    assert rows[0] == before[0]
    assert SETTINGS_EXTRA in text
    assert env.handlers.registry.get("sample") is served
    assert env.client.get("/sources/sample/docs").status_code == 200
    listed = env.client.get("/settings/sources").json()["sources"]
    assert [row["outsideRead"] for row in listed if row["id"] == "extra"] == [False]


def test_normal_when_row_without_id(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """id を省いた行を配信元の設定の name で指す（正常系）。"""
    # 準備
    notes = make_source("notes", sample_files(**{"project-index.yaml": sample_config(name="notes")}))
    env = make_server(make_source("sample"))
    _append_unnamed_row(env, notes)
    version = _version(env)
    # 実行
    response = env.client.patch(
        "/settings/sources/notes",
        json={"expectedVersion": version, "source": {"enabled": False}},
    )
    # 検証
    rows = load_yaml(env.settings_path.read_text(encoding="utf-8"))["sources"]
    assert response.status_code == 200
    assert ("notes", "disabled") in [
        (row["id"], row["status"]) for row in response.json()["sources"]
    ]
    assert rows[1]["enabled"] is False
    assert "id" not in rows[1]


def test_error_when_version_outdated(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """取得した後に書き換えられた端末の設定への変更を断る（異常系）。"""
    # 準備
    env = make_server(make_source("sample"), make_source("extra"))
    version = _version(env)
    with env.settings_path.open("a", encoding="utf-8") as file:
        file.write("# memo\n")
    edited = _version(env)
    before = env.settings_path.read_text(encoding="utf-8")
    # 実行
    response = env.client.patch(
        "/settings/sources/extra",
        json={"expectedVersion": version, "source": {"outside_read": False}},
    )
    # 検証
    assert response.status_code == 409
    assert response.json()["current"] == edited
    assert env.settings_path.read_text(encoding="utf-8") == before


def test_error_when_row_not_found(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """指した ID の行が無い変更を断る（異常系）。"""
    # 準備
    env = make_server(make_source("sample"))
    before = env.settings_path.read_text(encoding="utf-8")
    # 実行
    response = env.client.patch(
        "/settings/sources/extra",
        json={"expectedVersion": _version(env), "source": {"enabled": False}},
    )
    # 検証
    assert response.status_code == 404
    assert response.json()["sourceId"] == "extra"
    assert env.settings_path.read_text(encoding="utf-8") == before


def test_error_when_schema_invalid(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """内容のバージョンが無い変更と、配信元の ID が変わる変更と、変更後がスキーマに通らない変更を断る（異常系）。"""
    # 準備
    notes = make_source("notes", sample_files(**{"project-index.yaml": sample_config(name="notes")}))
    memo = make_source("memo", sample_files(**{"project-index.yaml": sample_config(name="memo")}))
    env = make_server(make_source("sample"), make_source("extra"))
    _append_unnamed_row(env, notes)
    version = _version(env)
    before = env.settings_path.read_text(encoding="utf-8")
    # 実行
    missing = env.client.patch("/settings/sources/extra", json={"source": {"enabled": False}})
    empty_glob = env.client.patch(
        "/settings/sources/extra",
        json={"expectedVersion": version, "source": {"scope": {"read": [""]}}},
    )
    with_id = env.client.patch(
        "/settings/sources/extra",
        json={"expectedVersion": version, "source": {"id": "other"}},
    )
    id_change = env.client.patch(
        "/settings/sources/notes",
        json={"expectedVersion": version, "source": {"config": [str(memo.config[0])]}},
    )
    # 検証
    assert missing.status_code == 422
    assert empty_glob.status_code == 422
    assert with_id.status_code == 422
    assert id_change.status_code == 422
    assert missing.json()["errors"]
    assert empty_glob.json()["errors"]
    assert with_id.json()["errors"]
    assert id_change.json()["errors"][0]["path"] == "source.config"
    assert env.settings_path.read_text(encoding="utf-8") == before


def test_error_when_cross_origin(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """ブラウザからの別のオリジンの変更を断る（異常系）。"""
    # 準備
    env = make_server(make_source("sample"), make_source("extra"))
    before = env.settings_path.read_bytes()
    # 実行
    response = env.client.patch(
        "/settings/sources/extra",
        json={"expectedVersion": _version(env), "source": {"enabled": False}},
        headers={"Origin": "http://127.0.0.1:9999"},
    )
    # 検証
    assert response.status_code == 403
    assert env.settings_path.read_bytes() == before

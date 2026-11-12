from __future__ import annotations

from typing import TYPE_CHECKING, Any

from project_index.shared.yaml_io import load_yaml

if TYPE_CHECKING:
    from collections.abc import Callable

SETTINGS_EXTRA = "# 取り込みの保持日数（コメントは保つ）\nseen_retention_days: 5\n"


def _version(env: Any) -> str:
    """端末の設定の取得の内容のバージョンを返す。"""
    return env.client.get("/settings/sources").json()["version"]


def test_normal(make_source: Callable[..., Any], make_server: Callable[..., Any]) -> None:
    """指した行だけを削除し、その配信元を配信から除外する（正常系）。"""
    # 準備
    extra = make_source("extra")
    env = make_server(make_source("sample"), extra, settings_extra=SETTINGS_EXTRA)
    before = load_yaml(env.settings_path.read_text(encoding="utf-8"))["sources"][0]
    folder_before = sorted(path.name for path in extra.folder.rglob("*"))
    served = env.handlers.registry.get("sample")
    version = _version(env)
    # 実行
    response = env.client.delete(f"/settings/sources/extra?expectedVersion={version}")
    # 検証
    text = env.settings_path.read_text(encoding="utf-8")
    body = response.json()
    assert response.status_code == 200
    assert body["version"] != version
    assert [row["id"] for row in body["sources"]] == ["sample"]
    assert load_yaml(text)["sources"] == [before]
    assert SETTINGS_EXTRA in text
    assert sorted(path.name for path in extra.folder.rglob("*")) == folder_before
    assert env.client.get("/sources/extra/docs").status_code == 404
    assert env.client.get("/sources/sample/docs").status_code == 200
    assert env.handlers.registry.get("sample") is served


def test_error_when_version_outdated(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """取得した後に書き換えられた端末の設定からの削除を断る（異常系）。"""
    # 準備
    env = make_server(make_source("sample"), make_source("extra"))
    version = _version(env)
    with env.settings_path.open("a", encoding="utf-8") as file:
        file.write("# memo\n")
    edited = _version(env)
    before = env.settings_path.read_text(encoding="utf-8")
    # 実行
    response = env.client.delete(f"/settings/sources/extra?expectedVersion={version}")
    # 検証
    assert response.status_code == 409
    assert response.json()["current"] == edited
    assert env.settings_path.read_text(encoding="utf-8") == before
    assert env.client.get("/sources/extra/docs").status_code == 200


def test_error_when_row_not_found(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """指した ID の行が無い削除を断る（異常系）。"""
    # 準備
    env = make_server(make_source("sample"))
    before = env.settings_path.read_text(encoding="utf-8")
    # 実行
    response = env.client.delete(f"/settings/sources/extra?expectedVersion={_version(env)}")
    # 検証
    assert response.status_code == 404
    assert env.settings_path.read_text(encoding="utf-8") == before


def test_error_when_version_missing(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """expectedVersion が無い削除を断る（異常系）。"""
    # 準備
    env = make_server(make_source("sample"), make_source("extra"))
    before = env.settings_path.read_text(encoding="utf-8")
    # 実行
    response = env.client.delete("/settings/sources/extra")
    # 検証
    assert response.status_code == 400
    assert env.settings_path.read_text(encoding="utf-8") == before


def test_error_when_cross_origin(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """ブラウザからの別のオリジンの削除を断る（異常系）。"""
    # 準備
    env = make_server(make_source("sample"), make_source("extra"))
    before = env.settings_path.read_bytes()
    # 実行
    response = env.client.delete(
        f"/settings/sources/extra?expectedVersion={_version(env)}",
        headers={"Origin": "http://127.0.0.1:9999"},
    )
    # 検証
    assert response.status_code == 403
    assert env.settings_path.read_bytes() == before

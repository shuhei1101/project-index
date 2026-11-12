from __future__ import annotations

from typing import TYPE_CHECKING, Any

from project_index.features.settings.query import load_terminal_config
from project_index.shared.yaml_io import load_yaml as load_yaml_value

if TYPE_CHECKING:
    from collections.abc import Callable


def load_yaml(text: str) -> Any:
    """形の分かっている YAML の文字列を読む。"""
    return load_yaml_value(text)


ORIGIN = {"Origin": "http://127.0.0.1:8786"}
SETTINGS_EXTRA = "# 取り込みの保持日数（コメントは保つ）\nseen_retention_days: 5\n"
BROKEN_CONFIG = "name: broken\ndocuments:\n  - id: sample\n    schema: schemas/sample.schema.yaml\n"


def _row(source: Any, **overrides: Any) -> dict[str, Any]:
    """PUT の本文の `sources[]` の 1 行を作る。"""
    row: dict[str, Any] = {
        "id": source.id,
        "config": [str(path) for path in source.config],
        "scope": {"read": [str(path) for path in source.scope_read]},
    }
    row.update(overrides)
    return row


def test_normal(make_source: Callable[..., Any], make_server: Callable[..., Any]) -> None:
    """配信元を追加して保存し、再起動せずに配信する（正常系）。"""
    # 準備
    sample = make_source("sample")
    extra = make_source("extra")
    env = make_server(sample, settings_extra=SETTINGS_EXTRA)
    sample_before = load_terminal_config(env.settings_path).sources[0]
    # 実行
    response = env.client.put(
        "/settings/sources",
        json={"sources": [_row(sample), _row(extra, config=str(extra.config[0]))]},
        headers=ORIGIN,
    )
    # 検証
    text = env.settings_path.read_text(encoding="utf-8")
    docs = env.client.get("/sources/extra/docs")
    described = env.call("describe", cwd=str(extra.folder))
    assert response.status_code == 200
    assert [(row["id"], row["status"]) for row in response.json()["sources"]] == [
        ("sample", "serving"),
        ("extra", "serving"),
    ]
    saved = load_terminal_config(env.settings_path)
    assert [entry.id for entry in saved.sources] == ["sample", "extra"]
    assert saved.sources[0] == sample_before
    assert SETTINGS_EXTRA in text
    assert load_yaml(text)["sources"][1]["config"] == [str(extra.config[0])]
    assert docs.status_code == 200
    assert "extra" in described.text


def test_normal_when_source_disabled(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """enabled: false で保存し、配信を止める（正常系）。"""
    # 準備
    sample = make_source("sample")
    extra = make_source("extra")
    env = make_server(sample, extra)
    # 実行
    response = env.client.put(
        "/settings/sources",
        json={"sources": [_row(sample), _row(extra, enabled=False)]},
        headers=ORIGIN,
    )
    # 検証
    text = env.settings_path.read_text(encoding="utf-8")
    assert response.status_code == 200
    assert {row["id"]: row["status"] for row in response.json()["sources"]} == {
        "sample": "serving",
        "extra": "disabled",
    }
    assert "enabled: false" in text
    assert env.client.get("/sources/extra/docs").status_code == 404
    assert env.client.get("/sources/sample/docs").status_code == 200


def test_normal_when_source_deleted(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """行を除いて保存し、配信元のフォルダは残す（正常系）。"""
    # 準備
    sample = make_source("sample")
    extra = make_source("extra")
    env = make_server(sample, extra)
    extra_files = sorted(str(path) for path in extra.folder.rglob("*.yaml"))
    # 実行
    response = env.client.put("/settings/sources", json={"sources": [_row(sample)]}, headers=ORIGIN)
    # 検証
    text = env.settings_path.read_text(encoding="utf-8")
    assert response.status_code == 200
    assert "id: extra" not in text
    assert "id: sample" in text
    assert sorted(str(path) for path in extra.folder.rglob("*.yaml")) == extra_files
    assert env.client.get("/sources/extra/docs").status_code == 404


def test_normal_when_added_source_invalid(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """端末の設定は保存し、読み直しの検証で配信元を外す（正常系）。"""
    # 準備
    sample = make_source("sample")
    broken = make_source("broken", {"project-index.yaml": BROKEN_CONFIG})
    env = make_server(sample)
    # 実行
    response = env.client.put(
        "/settings/sources",
        json={"sources": [_row(sample), _row(broken)]},
        headers=ORIGIN,
    )
    # 検証
    rows = {row["id"]: row for row in response.json()["sources"]}
    assert response.status_code == 200
    assert rows["broken"]["status"] == "not_served"
    assert any(error["path"] == "documents[0].paths" for error in rows["broken"]["errors"])
    assert "id: broken" in env.settings_path.read_text(encoding="utf-8")
    assert env.client.get("/sources/broken/docs").status_code == 404
    assert env.client.get("/sources/sample/docs").status_code == 200


def test_error_when_cross_origin(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """画面と別のオリジンからの保存を断る（異常系）。"""
    # 準備
    sample = make_source("sample")
    extra = make_source("extra")
    env = make_server(sample)
    before = env.settings_path.read_bytes()
    body = {"sources": [_row(sample), _row(extra)]}
    # 実行
    cross_origin = env.client.put(
        "/settings/sources", json=body, headers={"Origin": "http://127.0.0.1:9999"}
    )
    cross_site = env.client.put(
        "/settings/sources", json=body, headers={"Sec-Fetch-Site": "cross-site"}
    )
    # 検証
    assert cross_origin.status_code == 403
    assert cross_site.status_code == 403
    assert env.settings_path.read_bytes() == before
    assert env.client.get("/sources/sample/docs").status_code == 200


def test_error_when_schema_invalid(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """スキーマに通らない保存を断り、違反を全て返す（異常系）。"""
    # 準備
    sample = make_source("sample")
    extra = make_source("extra")
    env = make_server(sample)
    snapshot = env.settings_path.read_bytes()
    body = {
        "sources": [
            _row(sample),
            _row(extra, id="Sample Docs", scope={"read": [""]}),
        ]
    }
    # 実行
    response = env.client.put("/settings/sources", json=body, headers=ORIGIN)
    # 検証
    paths = [error["path"] for error in response.json()["errors"]]
    assert response.status_code == 422
    assert "sources[1].id" in paths
    assert any(path.startswith("sources[1].scope.read") for path in paths)
    assert all(error["reason"] for error in response.json()["errors"])
    assert env.settings_path.read_bytes() == snapshot
    assert env.client.get("/sources/sample/docs").status_code == 200


def test_normal_when_unsent_keys_kept(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """行に含めなかったキーを、ファイルの同じ配信元の行の今の値で残す（正常系）。"""
    # 準備
    sample = make_source("sample")
    extra = make_source("extra", outside_read=False, scope_write=[make_source("other").folder])
    env = make_server(sample, extra)
    before = load_terminal_config(env.settings_path).sources[1]
    # 実行
    response = env.client.put(
        "/settings/sources",
        json={"sources": [_row(sample, enabled=False), _row(extra)]},
        headers=ORIGIN,
    )
    # 検証
    rows = load_yaml(env.settings_path.read_text(encoding="utf-8"))["sources"]
    assert response.status_code == 200
    assert {row["id"]: row["status"] for row in response.json()["sources"]} == {
        "sample": "disabled",
        "extra": "serving",
    }
    assert rows[0]["enabled"] is False
    assert rows[1]["outside_read"] is False
    assert rows[1]["scope"]["write"] == before.scope.write


def test_normal_when_sent_keys_override(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """行に含めたキーは、ファイルの同じ配信元の行の値より送信した値で記載する（正常系）。"""
    # 準備
    sample = make_source("sample")
    extra = make_source("extra", outside_read=False)
    env = make_server(sample, extra)
    # 実行
    response = env.client.put(
        "/settings/sources",
        json={"sources": [_row(sample), _row(extra, outside_read=True)]},
        headers=ORIGIN,
    )
    listed = env.client.get("/settings/sources")
    # 検証
    rows = load_yaml(env.settings_path.read_text(encoding="utf-8"))["sources"]
    assert response.status_code == 200
    assert "outside_read" not in rows[1]
    assert {row["id"]: row["outsideRead"] for row in listed.json()["sources"]}["extra"] is True


UNKNOWN_KEY_EXTRA = "# MindStella の設定\nmindstella:\n  threads: 3  # 同時に動かす数\n"


def test_normal_when_unknown_top_level_key_kept(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """最上位の知らないキーを違反にせずに保存し、ファイルの値とコメントを残して警告で返す（正常系）。"""
    # 準備
    sample = make_source("sample")
    env = make_server(sample, settings_extra=UNKNOWN_KEY_EXTRA)
    # 実行
    response = env.client.put("/settings/sources", json={"sources": [_row(sample)]})
    # 検証
    body = response.json()
    assert response.status_code == 200
    assert [(row["id"], row["status"]) for row in body["sources"]] == [("sample", "serving")]
    assert [warning["path"] for warning in body["warnings"]] == ["mindstella"]
    assert UNKNOWN_KEY_EXTRA in env.settings_path.read_text(encoding="utf-8")

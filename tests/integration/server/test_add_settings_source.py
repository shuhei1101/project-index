from __future__ import annotations

from typing import TYPE_CHECKING, Any

from project_index.shared.yaml_io import load_yaml as load_yaml_value

if TYPE_CHECKING:
    from collections.abc import Callable


def load_yaml(text: str) -> Any:
    """形の分かっている YAML の文字列を読む。"""
    return load_yaml_value(text)


ORIGIN = {"Origin": "http://127.0.0.1:8786"}
SETTINGS_EXTRA = "# 取り込みの保持日数（コメントは保つ）\nseen_retention_days: 5\n"


def _row(source: Any, **overrides: Any) -> dict[str, Any]:
    """POST の本文の 1 行を作る。"""
    row: dict[str, Any] = {
        "id": source.id,
        "config": [str(path) for path in source.config],
        "scope": {"read": [str(path) for path in source.scope_read]},
    }
    row.update(overrides)
    return row


def test_normal(make_source: Callable[..., Any], make_server: Callable[..., Any]) -> None:
    """同じ id の行が無ければ末尾に追加し、配信元を読み直す（正常系）。"""
    # 準備
    sample = make_source("sample")
    extra = make_source("extra")
    env = make_server(sample, settings_extra=SETTINGS_EXTRA)
    before = load_yaml(env.settings_path.read_text(encoding="utf-8"))["sources"][0]
    # 実行
    response = env.client.post("/settings/sources", json={"source": _row(extra)}, headers=ORIGIN)
    # 検証
    text = env.settings_path.read_text(encoding="utf-8")
    body = response.json()
    assert response.status_code == 201
    assert body["result"] == "added"
    assert [(row["id"], row["status"]) for row in body["sources"]] == [
        ("sample", "serving"),
        ("extra", "serving"),
    ]
    rows = load_yaml(text)["sources"]
    assert [row["id"] for row in rows] == ["sample", "extra"]
    assert rows[0] == before
    assert SETTINGS_EXTRA in text
    assert env.client.get("/sources/extra/docs").status_code == 200


def test_error_when_same_id_exists(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """同じ id の行があれば追加せず、内容が同じかを返す（異常系）。"""
    # 準備
    sample = make_source("sample")
    extra = make_source("extra")
    env = make_server(sample, extra)
    before = env.settings_path.read_text(encoding="utf-8")
    # 実行
    same = env.client.post("/settings/sources", json={"source": _row(extra)}, headers=ORIGIN)
    other = env.client.post(
        "/settings/sources",
        json={"source": _row(extra, config=[str(sample.config[0])])},
        headers=ORIGIN,
    )
    # 検証
    assert same.status_code == 409
    assert same.json()["same"] is True
    assert other.status_code == 409
    assert other.json()["same"] is False
    assert env.settings_path.read_text(encoding="utf-8") == before


def test_error_when_schema_invalid(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """追加後の端末の設定がスキーマに通らない行を断る（異常系）。"""
    # 準備
    extra = make_source("extra")
    env = make_server(make_source("sample"))
    before = env.settings_path.read_text(encoding="utf-8")
    # 実行
    response = env.client.post(
        "/settings/sources", json={"source": _row(extra, id="Sample Docs")}, headers=ORIGIN
    )
    # 検証
    assert response.status_code == 422
    assert any(error["path"] == "sources[1].id" for error in response.json()["errors"])
    assert env.settings_path.read_text(encoding="utf-8") == before


UNKNOWN_KEY_EXTRA = "# MindStella の設定\nmindstella:\n  threads: 3  # 同時に動かす数\n"


def test_normal_when_unknown_top_level_key_kept(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """最上位の知らないキーを違反にせずに 1 行を追加し、ファイルの値とコメントを残して警告で返す（正常系）。"""
    # 準備
    sample = make_source("sample")
    extra = make_source("extra")
    env = make_server(sample, settings_extra=UNKNOWN_KEY_EXTRA)
    # 実行
    response = env.client.post("/settings/sources", json={"source": _row(extra)})
    # 検証
    body = response.json()
    assert response.status_code == 201
    assert body["result"] == "added"
    assert [warning["path"] for warning in body["warnings"]] == ["mindstella"]
    assert UNKNOWN_KEY_EXTRA in env.settings_path.read_text(encoding="utf-8")

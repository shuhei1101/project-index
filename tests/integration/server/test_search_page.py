from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


def _source(make_source: Callable[..., Any], sample_file_set: Callable[..., dict[str, str]]) -> Any:
    """文書 2 の本文だけが語「ページング」を含む sample を作る。"""
    files = sample_file_set(
        **{"docs/doc-2.yaml": "id: doc-2\nname: 文書 2\ndescription: 一覧のページングは先頭から\n"}
    )
    return make_source("sample", files)


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """語を含む文書だけを一致した箇所つきで返す（正常系）。"""
    # 準備
    env = make_server(_source(make_source, sample_file_set))
    # 実行
    found = env.client.get("/sources/sample/search", params={"q": "ページング"})
    body = found.json()
    opened = env.client.get(f"/sources/sample/docs/{body['items'][0]['path']}")
    # 検証
    assert found.status_code == 200
    assert body["totalCount"] == 1
    assert [item["path"] for item in body["items"]] == ["docs/doc-2"]
    assert any("ページング" in snippet for snippet in body["items"][0]["snippets"])
    assert opened.status_code == 200
    assert opened.json()["path"] == "docs/doc-2.yaml"


def test_error_when_query_invalid(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """空の語と長すぎる語を断る（異常系）。"""
    # 準備
    env = make_server(_source(make_source, sample_file_set))
    # 実行
    empty = env.client.get("/sources/sample/search", params={"q": ""})
    long = env.client.get("/sources/sample/search", params={"q": "x" * 201})
    # 検証
    assert empty.status_code == 400
    assert empty.json()["errors"][0]["path"] == "q"
    assert "at least 1 character" in empty.json()["errors"][0]["reason"]
    assert long.status_code == 400
    assert long.json()["errors"][0]["path"] == "q"
    assert "at most 200 characters" in long.json()["errors"][0]["reason"]


def test_error_when_not_found(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """無い配信元・解決できないリビジョンを断る（異常系）。"""
    # 準備
    env = make_server(_source(make_source, sample_file_set))
    # 実行
    unknown = env.client.get("/sources/unknown/search", params={"q": "a"})
    no_ref = env.client.get("/sources/sample/search", params={"q": "a", "ref": "no-such-branch"})
    # 検証
    assert unknown.status_code == 404
    assert "配信元" in unknown.json()["detail"]
    assert "unknown" in unknown.json()["detail"]
    assert no_ref.status_code == 404
    assert "no-such-branch" in no_ref.json()["detail"]

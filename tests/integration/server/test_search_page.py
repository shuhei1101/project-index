from __future__ import annotations

from typing import TYPE_CHECKING, Any

from project_index.integrations.git import GIT_ARCHIVE_TIMEOUT_SEC

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
    by_id = env.client.get(
        f"/sources/sample/docs/{body['items'][0]['filePath']}",
        params={"id": body["items"][0]["id"]},
    )
    # 検証
    assert found.status_code == 200
    assert body["totalCount"] == 1
    assert [item["path"] for item in body["items"]] == ["docs/doc-2"]
    assert any("ページング" in snippet for snippet in body["items"][0]["snippets"])
    assert opened.status_code == 200
    assert opened.json()["path"] == "docs/doc-2.yaml"
    assert body["items"][0]["id"] == "doc-2"
    assert body["items"][0]["filePath"] == "docs/doc-2.yaml"
    assert by_id.status_code == 200
    assert by_id.json()["metadata"]["id"] == "doc-2"


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


def test_error_when_revision_export_times_out(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    time_out_archive: Callable[..., list[str]],
) -> None:
    """親の commit の書き出しが上限を超えたとき、止めた処理と理由を返す（異常系）。"""
    # 準備
    source = _source(make_source, sample_file_set)
    parent = run_git(source.folder, "rev-parse", "HEAD").strip()
    commit_all(source.folder, {"docs/doc-3.yaml": "id: doc-3\nname: 文書 3\n"}, "docs: 追加")
    time_out_archive(commits={parent})
    env = make_server(source)
    env.wait_background()
    # 実行
    response = env.client.get("/sources/sample/search", params={"q": "ページング", "ref": parent})
    # 検証
    body = response.json()
    assert response.status_code == 504
    assert body["title"] == "RevisionExportTimeoutError"
    assert body["operation"] == "revision_export"
    assert body["commit"] == parent
    assert body["limitSec"] == GIT_ARCHIVE_TIMEOUT_SEC
    assert "リビジョンの書き出し" in body["detail"]
    assert f"{GIT_ARCHIVE_TIMEOUT_SEC:g} 秒" in body["detail"]


ASSETS_ROW = (
    "  - id: assets\n"
    "    paths: [assets/*.yaml]\n"
    "    schema: schemas/sample.schema.yaml\n"
    "    metadata: {status: state}\n"
    "    search_exclude: {field: status, op: eq, values: [inactive]}\n"
)


def test_normal_when_search_excluded(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """行の search_exclude に該当する文書を既定の結果から除き、include_excluded=true のときだけ excluded: true を付けて返却する（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(ASSETS_ROW),
            "assets/a1.yaml": "id: a1\nname: 素材 1\nstate: active\ndescription: 夕焼けの背景\n",
            "assets/a2.yaml": "id: a2\nname: 素材 2\nstate: inactive\ndescription: 夕焼けの古い背景\n",
        }
    )
    env = make_server(make_source("sample", files))
    # 実行
    default = env.client.get("/sources/sample/search", params={"q": "夕焼け"}).json()
    included = env.client.get(
        "/sources/sample/search", params={"q": "夕焼け", "include_excluded": "true"}
    ).json()
    # 検証
    assert default["totalCount"] == 1
    assert [item["id"] for item in default["items"]] == ["a1"]
    assert default["excludedCount"] == 1
    assert included["totalCount"] == 2
    assert [(item["id"], item.get("excluded")) for item in included["items"]] == [
        ("a1", None),
        ("a2", True),
    ]
    assert "excludedCount" not in included

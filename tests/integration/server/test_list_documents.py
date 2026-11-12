from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.integration.server.conftest import FILES_SCHEMA_TEMPLATE

if TYPE_CHECKING:
    from collections.abc import Callable

DESIGN_SCHEMA = (
    "type: object\n"
    "properties:\n"
    "  id:\n"
    "    type: string\n"
    "  title:\n"
    "    $ref: common.schema.yaml#/$defs/text\n"
)
COMMON_SCHEMA = "$defs:\n  text:\n    type: string\n"
CONFIG = (
    "name: sample\n"
    "default_ref: main\n"
    "documents:\n"
    "  - id: design\n"
    "    paths: [design/*.yaml]\n"
    "    schema: schemas/design.schema.yaml\n"
    "  - id: notes\n"
    "    paths: [notes/files.yaml]\n"
    "    schema: schemas/files.schema.yaml\n"
    "    records: files\n"
    "    body_file: path\n"
)


def main_files() -> dict[str, str]:
    """種類 `design` の YAML 2 件と、管理用の YAML の行の文書 1 件を持つ配信元のファイル一式を返す。"""
    return {
        "project-index.yaml": CONFIG,
        "schemas/design.schema.yaml": DESIGN_SCHEMA,
        "schemas/common.schema.yaml": COMMON_SCHEMA,
        "schemas/files.schema.yaml": FILES_SCHEMA_TEMPLATE.read_text(encoding="utf-8"),
        "design/D-1.yaml": "id: D-1\nname: 設計 1\ndescription: 1 件目\ntags: [a]\ntitle: 最初\n",
        "design/D-2.yaml": "id: D-2\nname: 設計 2\ntitle: 2 件目\n",
        "notes/files.yaml": "files:\n  - path: guide.md\n    name: 手引き\n",
        "notes/guide.md": "# 手引き\n\n本文\n",
    }


def test_normal(make_source: Callable[..., Any], make_server: Callable[..., Any]) -> None:
    """指定のリビジョンの文書の ID・パス・種類・メタデータを返す（正常系）。"""
    # 準備
    env = make_server(make_source("sample", main_files(), branch="main"))
    # 実行
    response = env.client.get("/sources/sample/docs")
    # 検証
    body = response.json()
    assert response.status_code == 200
    assert body["ref"] == "main"
    assert [(row["kind"], row["path"]) for row in body["documents"]] == [
        ("design", "design/D-1.yaml"),
        ("design", "design/D-2.yaml"),
        ("notes", "notes/files.yaml"),
    ]
    first = body["documents"][0]
    assert first == {
        "id": "D-1",
        "path": "design/D-1.yaml",
        "kind": "design",
        "name": "設計 1",
        "description": "1 件目",
        "tags": ["a"],
        "visibility": None,
        "bodyPath": None,
        "version": first["version"],
        "value": None,
    }
    assert isinstance(first["version"], str)
    assert first["version"]
    assert body["documents"][2]["bodyPath"] == "notes/guide.md"


def test_normal_when_values_requested(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """`values` を指したときだけ、各文書の値を返す（正常系）。"""
    # 準備
    env = make_server(make_source("sample", main_files(), branch="main"))
    # 実行
    response = env.client.get("/sources/sample/docs", params={"values": "true"})
    first = env.client.get("/sources/sample/docs/design/D-1.yaml")
    row = env.client.get("/sources/sample/docs/notes/guide.md")
    # 検証
    documents = response.json()["documents"]
    assert response.status_code == 200
    assert documents[0]["value"] == first.json()["value"]
    assert documents[0]["value"]["title"] == "最初"
    assert documents[2]["value"] == row.json()["value"]
    assert documents[2]["value"] == {"path": "guide.md", "name": "手引き"}


def test_normal_when_ref_given(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """ref の文書の一覧を返す（正常系）。"""
    # 準備
    source = make_source("sample", main_files(), branch="main")
    parent = run_git(source.folder, "rev-parse", "HEAD").strip()
    commit_all(
        source.folder,
        {
            "design/D-3.yaml": "id: D-3\nname: 設計 3\n",
            "design/D-1.yaml": "id: D-1\nname: 設計 1\ndescription: 1 件目\ntags: [a]\ntitle: 変えた\n",
        },
        "docs: 追加",
    )
    env = make_server(source)
    # 実行
    response = env.client.get("/sources/sample/docs", params={"ref": parent})
    latest = env.client.get("/sources/sample/docs")
    # 検証
    old = {row["path"]: row["version"] for row in response.json()["documents"]}
    new = {row["path"]: row["version"] for row in latest.json()["documents"]}
    assert response.status_code == 200
    assert "design/D-3.yaml" not in old
    assert "design/D-1.yaml" in old
    assert old["design/D-2.yaml"] == new["design/D-2.yaml"]
    assert old["design/D-1.yaml"] != new["design/D-1.yaml"]


def test_error_when_not_found(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """無い配信元・配信していない配信元・解決できないリビジョンを断る（異常系）。"""
    # 準備
    env = make_server(make_source("sample", main_files(), branch="main"))
    # 実行
    unknown = env.client.get("/sources/unknown/docs")
    no_ref = env.client.get("/sources/sample/docs", params={"ref": "no-such-branch"})
    # 検証
    assert unknown.status_code == 404
    assert unknown.json()["missing"] == "source"
    assert no_ref.status_code == 404
    assert no_ref.json()["missing"] == "ref"
    assert "no-such-branch" in no_ref.json()["detail"]

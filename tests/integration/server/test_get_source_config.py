from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

NAV = (
    "nav:\n"
    "  tabs:\n"
    "    - title: 文書\n"
    "      items:\n"
    "        - auto:\n"
    "            document: sample\n"
)
DECISIONS = "decisions:\n  folders: [tmp/a]\n"
GITHUB = "github:\n  repository: owner/sample\n  issue_labels: [docs]\n"
DIFF = "diff:\n  ignore_keys: [updated, rev]\n"
LOCAL_GITHUB = "github:\n  repository: owner/local\n  issue_labels: [local]\n"


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """配信元の設定のうち、画面が使うキーを返す（正常系）。"""
    # 準備
    config = sample_config_text(NAV + DECISIONS + GITHUB + DIFF)
    sample = make_source("sample", sample_file_set(**{"project-index.yaml": config}))
    files = sample_file_set(
        **{"project-index.yaml": sample_config_text(name="merged"), "local.yaml": LOCAL_GITHUB}
    )
    merged = make_source("merged", files, config_names=("project-index.yaml", "local.yaml"))
    env = make_server(sample, merged)
    # 実行
    response = env.client.get("/sources/sample/config")
    overlaid = env.client.get("/sources/merged/config")
    # 検証
    body = response.json()
    assert response.status_code == 200
    assert body["nav"]["tabs"][0]["title"] == "文書"
    assert [row["id"] for row in body["documents"]] == ["sample"]
    assert body["documents"][0]["schema"] == "schemas/sample.schema.yaml"
    assert body["decisions"]["folders"] == ["tmp/a"]
    assert body["github"] == {"repository": "owner/sample", "issueLabels": ["docs"]}
    assert body["diff"] == {"ignore_keys": ["updated", "rev"]}
    assert body["schemas"] is None
    assert overlaid.json()["github"]["repository"] == "owner/local"
    assert overlaid.json()["diff"] == {"ignore_keys": ["updated"]}


SCHEMA_CONFIG = (
    "name: sample\n"
    "default_ref: develop\n"
    "documents:\n"
    "  - id: design\n"
    "    paths: [design/*.yaml]\n"
    "    schema: schemas/design.schema.yaml\n"
    "  - id: files_guide\n"
    "    paths: [files.yaml]\n"
    "    schema: schemas/files.schema.yaml\n"
    "    records: files\n"
    "    body_file: path\n"
)
# 循環しない定義 title と、自分を指す循環する定義 node を持つ
NODE_DEFS = (
    "$defs:\n"
    "  title:\n"
    "    type: string\n"
    "  node:\n"
    "    type: object\n"
    "    properties:\n"
    "      children:\n"
    "        type: array\n"
    "        items:\n"
    "          $ref: '#/$defs/node'\n"
)
DESIGN_SCHEMA = (
    "type: object\n"
    "properties:\n"
    "  title:\n"
    "    $ref: '#/$defs/title'\n"
    "  tree:\n"
    "    $ref: '#/$defs/node'\n"
) + NODE_DEFS
FILES_SCHEMA = (
    "type: object\n"
    "properties:\n"
    "  files:\n"
    "    type: array\n"
    "    items:\n"
    "      type: object\n"
    "      properties:\n"
    "        path:\n"
    "          type: string\n"
    "        tree:\n"
    "          $ref: '#/$defs/node'\n"
) + NODE_DEFS


def test_normal_when_schemas_requested(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """`schemas` を指したときだけ、`documents[]` の行ごとの `$ref` を解いた種類のスキーマを返す（正常系）。"""
    # 準備
    files = {
        "project-index.yaml": SCHEMA_CONFIG,
        "schemas/design.schema.yaml": DESIGN_SCHEMA,
        "schemas/files.schema.yaml": FILES_SCHEMA,
        "design/D-1.yaml": "id: D-1\ntitle: 設計\n",
        "files.yaml": "files:\n  - path: guide.md\n",
        "guide.md": "# 手引き\n",
    }
    env = make_server(make_source("sample", files))
    # 実行
    response = env.client.get("/sources/sample/config", params={"schemas": "true"})
    row = env.client.get("/sources/sample/docs/guide.md")
    # 検証
    schemas = response.json()["schemas"]
    assert response.status_code == 200
    assert list(schemas) == ["design", "files_guide"]
    design = schemas["design"]
    assert design["properties"]["title"] == {"type": "string"}
    assert design["properties"]["tree"]["properties"]["children"]["items"] == {
        "$ref": "#/$defs/node"
    }
    assert "node" in design["$defs"]
    files_guide = schemas["files_guide"]
    assert files_guide["properties"]["path"] == {"type": "string"}
    assert files_guide["properties"]["tree"]["properties"]["children"]["items"] == {
        "$ref": "#/$defs/node"
    }
    assert "node" in files_guide["$defs"]
    assert files_guide == row.json()["schema"]


def test_error_when_source_not_found(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """無い配信元・配信していない配信元を断る（異常系）。"""
    # 準備
    broken_config = "name: broken\ndocuments:\n  - id: sample\n"
    broken = make_source("broken", sample_file_set(**{"project-index.yaml": broken_config}))
    env = make_server(make_source("sample"), broken)
    # 実行
    unknown = env.client.get("/sources/unknown/config")
    not_served = env.client.get("/sources/broken/config")
    # 検証
    assert unknown.status_code == 404
    assert unknown.headers["content-type"].startswith("application/problem+json")
    assert unknown.json()["missing"] == "source"
    assert "unknown" in unknown.json()["detail"]
    assert not_served.status_code == 404
    assert not_served.json()["missing"] == "not_served"
    assert not_served.json()["errors"]

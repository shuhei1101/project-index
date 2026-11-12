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
LOCAL_GITHUB = "github:\n  repository: owner/local\n  issue_labels: [local]\n"


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """配信元の設定のうち、画面が使うキーを返す（正常系）。"""
    # 準備
    config = sample_config_text(NAV + DECISIONS + GITHUB)
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
    assert overlaid.json()["github"]["repository"] == "owner/local"


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

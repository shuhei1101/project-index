from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.integration.server.test_list_documents import main_files

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

PROMPT_CONFIG = (
    "name: sample\n"
    "default_ref: main\n"
    "documents:\n"
    "  - id: prompt\n"
    "    paths: [prompts/*.yaml]\n"
    "    schema: schemas/prompt.schema.yaml\n"
    "    converter: prompt_md\n"
    "converters:\n"
    "  - id: prompt_md\n"
    "    run: [python3, scripts/convert_prompt.py]\n"
)
PROMPT_SCHEMA = "type: object\n"
# 呼ばれた回数を記録し、`broken` を含む文書は終了コード 1 で終える
CONVERT_PROMPT = (
    "import sys\n"
    "text = sys.stdin.read()\n"
    "with open({calls!r}, 'a', encoding='utf-8') as log:\n"
    "    log.write('called\\n')\n"
    "if 'broken' in text:\n"
    "    print('変換に失敗した', file=sys.stderr)\n"
    "    sys.exit(1)\n"
    "print('# 変換したプロンプト')\n"
)


def test_normal(make_source: Callable[..., Any], make_server: Callable[..., Any]) -> None:
    """文書の値・種類のスキーマ・メタデータを返す（正常系）。"""
    # 準備
    env = make_server(make_source("sample", main_files(), branch="main"))
    # 実行
    response = env.client.get("/sources/sample/docs/design/D-1.yaml")
    # 検証
    body = response.json()
    assert response.status_code == 200
    assert body["value"]["title"] == "最初"
    assert body["schema"]["properties"]["title"] == {"type": "string"}
    assert body["metadata"]["id"] == "D-1"
    assert body["metadata"]["kind"] == "design"
    assert body["metadata"]["name"] == "設計 1"
    assert body["metadata"]["tags"] == ["a"]
    assert body["markdown"] is None
    assert body["conversionError"] is None
    assert body["body"] is None
    assert body["bodyPath"] is None
    assert body["updatedAt"]


def test_normal_when_ref_given(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """ref の文書の値を返す（正常系）。"""
    # 準備
    source = make_source("sample", main_files(), branch="main")
    parent = run_git(source.folder, "rev-parse", "HEAD").strip()
    commit_all(
        source.folder, {"design/D-1.yaml": "id: D-1\nname: 設計 1\ntitle: 変えた\n"}, "docs: 改題"
    )
    env = make_server(source)
    # 実行
    response = env.client.get("/sources/sample/docs/design/D-1.yaml", params={"ref": parent})
    latest = env.client.get("/sources/sample/docs/design/D-1.yaml")
    # 検証
    assert response.status_code == 200
    assert response.json()["ref"] == parent
    assert response.json()["value"]["title"] == "最初"
    assert latest.json()["value"]["title"] == "変えた"


def test_normal_when_body_path_given(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """管理用の YAML の行の文書を、本文のファイルのパスで引く（正常系）。"""
    # 準備
    env = make_server(make_source("sample", main_files(), branch="main"))
    # 実行
    response = env.client.get("/sources/sample/docs/notes/guide.md")
    # 検証
    body = response.json()
    assert response.status_code == 200
    assert body["value"]["path"] == "guide.md"
    assert body["body"] == "# 手引き\n\n本文\n"
    assert body["bodyPath"] == "notes/guide.md"


def test_normal_when_converter_kind(
    make_source: Callable[..., Any], make_server: Callable[..., Any], tmp_path: Path
) -> None:
    """converters[] を指す種類は、スクリプトが出した Markdown を返す（正常系）。"""
    # 準備
    calls = tmp_path / "calls.log"
    files = {
        "project-index.yaml": PROMPT_CONFIG,
        "schemas/prompt.schema.yaml": PROMPT_SCHEMA,
        "scripts/convert_prompt.py": CONVERT_PROMPT.format(calls=str(calls)),
        "prompts/a.yaml": "id: a\nname: 普通\n",
        "prompts/broken.yaml": "id: broken\nname: 壊れる\n",
    }
    env = make_server(make_source("sample", files, branch="main"))
    # 実行
    converted = env.client.get("/sources/sample/docs/prompts/a.yaml")
    failed = env.client.get("/sources/sample/docs/prompts/broken.yaml")
    called = calls.read_text(encoding="utf-8").count("called")
    again = env.client.get("/sources/sample/docs/prompts/a.yaml")
    # 検証
    assert converted.status_code == 200
    assert converted.json()["markdown"] == "# 変換したプロンプト\n"
    assert converted.json()["conversionError"] is None
    assert failed.status_code == 200
    error = failed.json()["conversionError"]
    assert error["reason"] == "exit"
    assert "scripts/convert_prompt.py" in error["script"]
    assert "変換に失敗した" in error["detail"]
    assert failed.json()["markdown"] is None
    assert again.json()["markdown"] == "# 変換したプロンプト\n"
    assert calls.read_text(encoding="utf-8").count("called") == called


def test_error_when_not_found(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """無い配信元・解決できないリビジョン・無い文書を断る（異常系）。"""
    # 準備
    env = make_server(make_source("sample", main_files(), branch="main"))
    # 実行
    unknown = env.client.get("/sources/unknown/docs/a.yaml")
    no_ref = env.client.get(
        "/sources/sample/docs/design/D-1.yaml", params={"ref": "no-such-branch"}
    )
    no_doc = env.client.get("/sources/sample/docs/no/such.yaml")
    # 検証
    assert (unknown.status_code, unknown.json()["missing"]) == (404, "source")
    assert (no_ref.status_code, no_ref.json()["missing"]) == (404, "ref")
    assert (no_doc.status_code, no_doc.json()["missing"]) == (404, "doc")

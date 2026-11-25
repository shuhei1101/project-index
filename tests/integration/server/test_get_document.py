from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING, Any

from project_index.integrations.git import GIT_ARCHIVE_TIMEOUT_SEC
from tests.integration.server.test_list_documents import main_files

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

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


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """文書の値・種類のスキーマ・メタデータを返す（正常系）。"""
    # 準備（D-1 を変えた commit の後に、D-1 を変えない commit を積む）
    source = make_source("sample", main_files(), branch="main")
    commit_all(
        source.folder, {"design/D-2.yaml": "id: D-2\nname: 設計 2\ntitle: 後\n"}, "docs: D-2"
    )
    changed_at = run_git(source.folder, "log", "-1", "--format=%cI", "--", "design/D-1.yaml")
    env = make_server(source)
    # 実行
    response = env.client.get("/sources/sample/docs/design/D-1.yaml")
    listed = env.client.get("/sources/sample/docs", params={"common_keys": "true"})
    # 検証
    body = response.json()
    assert response.status_code == 200
    assert body["value"]["title"] == "最初"
    # `$ref` を解いた形
    assert body["schema"]["properties"]["title"] == {"type": "string"}
    assert body["metadata"]["id"] == "D-1"
    assert body["metadata"]["kind"] == "design"
    assert body["metadata"]["name"] == "設計 1"
    assert body["metadata"]["tags"] == ["a"]
    assert body["metadata"]["visibility"] == "internal"
    assert body["metadata"]["commonKeys"]["visibility"] == "internal"
    assert body["metadata"]["commonKeys"] == listed.json()["documents"][0]["commonKeys"]
    assert body["markdown"] is None
    assert body["conversionError"] is None
    assert body["body"] is None
    assert body["bodyPath"] is None
    assert datetime.fromisoformat(body["updatedAt"]) == datetime.fromisoformat(changed_at.strip())


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


# make_source の最初の commit（今の日時）より後にして、feature で変えた commit を D-1 の最後の変更にする
BRANCH_CHANGED_AT = "2030-10-02T12:00:00+09:00"
MAIN_CHANGED_AT = "2030-10-03T12:00:00+09:00"
MERGED_AT = "2030-10-04T12:00:00+09:00"


def test_normal_when_document_only_in_revision(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    write_files: Callable[[Path, dict[str, str]], None],
    run_git: Callable[..., str],
) -> None:
    """作業ツリーに無く、指したリビジョンのマージ commit で追加した文書を、そのマージ commit の日時で返却する（正常系）。"""
    # 準備（feature で D-1 を変え、main にも commit を追加してから、feature へ main をマージした commit で D-9・broken を追加する）
    source = make_source("sample", main_files(), branch="main")
    folder = source.folder
    run_git(folder, "checkout", "-b", "feature")
    write_files(folder, {"design/D-1.yaml": "id: D-1\nname: 設計 1\ntitle: feature で変えた\n"})
    run_git(folder, "add", "-A")
    run_git(
        folder,
        "commit",
        "-m",
        "docs: D-1",
        env={"GIT_AUTHOR_DATE": BRANCH_CHANGED_AT, "GIT_COMMITTER_DATE": BRANCH_CHANGED_AT},
    )
    run_git(folder, "checkout", "main")
    write_files(folder, {"design/D-2.yaml": "id: D-2\nname: 設計 2\ntitle: main で変えた\n"})
    run_git(folder, "add", "-A")
    run_git(
        folder,
        "commit",
        "-m",
        "docs: D-2",
        env={"GIT_AUTHOR_DATE": MAIN_CHANGED_AT, "GIT_COMMITTER_DATE": MAIN_CHANGED_AT},
    )
    run_git(folder, "checkout", "feature")
    run_git(folder, "merge", "--no-ff", "--no-commit", "main")
    write_files(
        folder,
        {
            "design/D-9.yaml": "id: D-9\nname: 設計 9\ntitle: マージで追加した\n",
            "design/broken.yaml": "id: [broken\n",
        },
    )
    run_git(folder, "add", "-A")
    run_git(
        folder,
        "commit",
        "-m",
        "merge",
        env={"GIT_AUTHOR_DATE": MERGED_AT, "GIT_COMMITTER_DATE": MERGED_AT},
    )
    run_git(folder, "checkout", "main")
    env = make_server(source)
    # 実行
    added = env.client.get("/sources/sample/docs/design/D-9.yaml", params={"ref": "feature"})
    broken = env.client.get("/sources/sample/docs/design/broken.yaml", params={"ref": "feature"})
    branch_only = env.client.get("/sources/sample/docs/design/D-1.yaml", params={"ref": "feature"})
    # 検証
    assert not (folder / "design" / "D-9.yaml").exists()
    assert not (folder / "design" / "broken.yaml").exists()
    assert added.status_code == 200
    assert added.json()["value"]["title"] == "マージで追加した"
    assert datetime.fromisoformat(added.json()["updatedAt"]) == datetime.fromisoformat(MERGED_AT)
    assert broken.status_code == 200
    error = broken.json()["conversionError"]
    assert error["file"] == "design/broken.yaml"
    assert error["line"] is not None
    assert error["column"] is not None
    assert datetime.fromisoformat(broken.json()["updatedAt"]) == datetime.fromisoformat(MERGED_AT)
    assert branch_only.status_code == 200
    assert datetime.fromisoformat(branch_only.json()["updatedAt"]) == datetime.fromisoformat(
        BRANCH_CHANGED_AT
    )


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


TERMS_CONFIG = (
    "name: sample\n"
    "default_ref: main\n"
    "documents:\n"
    "  - id: terms\n"
    "    paths: [terms.yaml]\n"
    "    schema: schemas/terms.schema.yaml\n"
    "    records: terms\n"
)
TERMS_SCHEMA = (
    "type: object\n"
    "properties:\n"
    "  terms:\n"
    "    type: array\n"
    "    items:\n"
    "      $ref: '#/$defs/term'\n"
    "$defs:\n"
    "  term:\n"
    "    type: object\n"
    "    properties:\n"
    "      id:\n"
    "        type: string\n"
)
TERMS = "terms:\n  - id: term-1\n    name: alpha\n  - id: term-2\n    name: beta\n"


def terms_files() -> dict[str, str]:
    """`body_file` の無い `records` の行 `term-1`・`term-2` を持つ配信元のファイル一式を返す。"""
    return {
        "project-index.yaml": TERMS_CONFIG,
        "schemas/terms.schema.yaml": TERMS_SCHEMA,
        "terms.yaml": TERMS,
    }


def test_normal_when_id_given(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """1 つの管理用の YAML の中の行の文書を、文書の ID で 1 つに選ぶ（正常系）。"""
    # 準備
    env = make_server(make_source("sample", terms_files(), branch="main"))
    # 実行
    chosen = env.client.get("/sources/sample/docs/terms.yaml", params={"id": "term-2"})
    default = env.client.get("/sources/sample/docs/terms.yaml")
    # 検証
    body = chosen.json()
    assert chosen.status_code == 200
    assert body["value"] == {"id": "term-2", "name": "beta"}
    assert body["metadata"]["id"] == "term-2"
    assert body["schema"]["$defs"]["term"]["properties"]["id"] == {"type": "string"}
    assert default.json()["metadata"]["id"] == "term-1"


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


COMMIT_CONFIG = (
    "name: sample\n"
    "default_ref: main\n"
    "documents:\n"
    "  - id: prompt\n"
    "    paths: [prompts/*.yaml]\n"
    "    schema: schemas/prompt.schema.yaml\n"
    "    converter: commit_md\n"
    "converters:\n"
    "  - id: commit_md\n"
    "    run: [python3, scripts/print_commit.py]\n"
    "    cache: false\n"
)
# 環境変数 PROJECT_INDEX_COMMIT の値（無ければ none）を出す
PRINT_COMMIT = "import os\nprint(os.environ.get('PROJECT_INDEX_COMMIT', 'none'))\n"


def test_normal_when_converter_given_commit(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Git の配信元の converters[] のスクリプトは、環境変数 PROJECT_INDEX_COMMIT で応答の ref を解いた commit を受け取る（正常系）。"""
    # 準備（main に 2 つの commit を追加し、サーバーの環境に outer を入れる）
    files = {
        "project-index.yaml": COMMIT_CONFIG,
        "schemas/prompt.schema.yaml": PROMPT_SCHEMA,
        "scripts/print_commit.py": PRINT_COMMIT,
        "prompts/a.yaml": "id: a\nname: 最初\n",
    }
    source = make_source("sample", files, branch="main")
    parent = run_git(source.folder, "rev-parse", "HEAD").strip()
    commit_all(source.folder, {"prompts/a.yaml": "id: a\nname: 変えた\n"}, "docs: 改題")
    head = run_git(source.folder, "rev-parse", "HEAD").strip()
    monkeypatch.setenv("PROJECT_INDEX_COMMIT", "outer")
    env = make_server(source)
    # 実行
    at_parent = env.client.get("/sources/sample/docs/prompts/a.yaml", params={"ref": parent})
    at_default = env.client.get("/sources/sample/docs/prompts/a.yaml")
    # 検証
    assert at_parent.status_code == 200
    assert at_parent.json()["markdown"] == f"{parent}\n"
    assert at_default.status_code == 200
    assert at_default.json()["markdown"] == f"{head}\n"


def test_error_when_not_found(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """無い配信元・配信していない配信元・解決できないリビジョン・無い文書を断る（異常系）。"""
    # 準備
    broken_config = "name: broken\ndocuments:\n  - id: sample\n"
    broken = make_source("broken", sample_file_set(**{"project-index.yaml": broken_config}))
    env = make_server(make_source("sample", main_files(), branch="main"), broken)
    # 実行
    unknown = env.client.get("/sources/unknown/docs/a.yaml")
    not_served = env.client.get("/sources/broken/docs/a.yaml")
    no_ref = env.client.get(
        "/sources/sample/docs/design/D-1.yaml", params={"ref": "no-such-branch"}
    )
    no_doc = env.client.get("/sources/sample/docs/no/such.yaml")
    no_id = env.client.get("/sources/sample/docs/design/D-1.yaml", params={"id": "no-such-id"})
    # 検証
    assert (unknown.status_code, unknown.json()["missing"]) == (404, "source")
    assert (not_served.status_code, not_served.json()["missing"]) == (404, "not_served")
    assert not_served.json()["errors"]
    assert (no_ref.status_code, no_ref.json()["missing"]) == (404, "ref")
    assert (no_doc.status_code, no_doc.json()["missing"]) == (404, "doc")
    assert (no_id.status_code, no_id.json()["missing"]) == (404, "doc")


def test_error_when_revision_export_times_out(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    time_out_archive: Callable[..., list[str]],
) -> None:
    """親の commit の書き出しが上限を超えたとき、止めた処理と理由を返す（異常系）。"""
    # 準備
    source = make_source("sample", main_files(), branch="main")
    parent = run_git(source.folder, "rev-parse", "HEAD").strip()
    commit_all(source.folder, {"design/D-3.yaml": "id: D-3\nname: 設計 3\n"}, "docs: 追加")
    time_out_archive(commits={parent})
    env = make_server(source)
    env.wait_background()
    # 実行
    response = env.client.get("/sources/sample/docs/design/D-1.yaml", params={"ref": parent})
    # 検証
    body = response.json()
    assert response.status_code == 504
    assert body["title"] == "RevisionExportTimeoutError"
    assert body["operation"] == "revision_export"
    assert body["commit"] == parent
    assert body["limitSec"] == GIT_ARCHIVE_TIMEOUT_SEC
    assert "リビジョンの書き出し" in body["detail"]
    assert f"{GIT_ARCHIVE_TIMEOUT_SEC:g} 秒" in body["detail"]
    assert list((env.state_dir / "snapshots").glob("*/*.tmp")) == []


def test_normal_when_disk_storage(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
    write_files: Callable[[Path, dict[str, str]], None],
) -> None:
    """disk の配信元は ref を無視して登録したフォルダの文書を返す（正常系）。"""
    # 準備（master には D-3 が無く、登録したフォルダにだけ D-3 を置く）
    company = make_source("company", main_files(), branch="main", storage="disk")
    run_git(company.folder, "branch", "master")
    write_files(company.folder, {"design/D-3.yaml": "id: D-3\nname: 設計 3\ntitle: 手元\n"})
    env = make_server(company)
    # 実行
    response = env.client.get("/sources/company/docs/design/D-3.yaml", params={"ref": "master"})
    # 検証
    body = response.json()
    assert response.status_code == 200
    assert body["ref"] == ""
    assert body["value"]["title"] == "手元"


# 呼ばれた回数を記録し、`{heading}` の見出しを出す
CONVERT_VERSION = (
    "with open({calls!r}, 'a', encoding='utf-8') as log:\n"
    "    log.write('called\\n')\n"
    "print({heading!r})\n"
)


def test_normal_when_converter_script_changed(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    write_files: Callable[[Path, dict[str, str]], None],
    tmp_path: Path,
) -> None:
    """変換のスクリプトのファイルを書き換えると、文書が変わらなくても次の取得から書き換えた後のスクリプトの Markdown を返却する（正常系）。"""
    # 準備（disk の配信元。`cache` を記載しない行のスクリプトは `# v1` を出す）
    calls = tmp_path / "calls.log"
    files = {
        "project-index.yaml": PROMPT_CONFIG,
        "schemas/prompt.schema.yaml": PROMPT_SCHEMA,
        "scripts/convert_prompt.py": CONVERT_VERSION.format(calls=str(calls), heading="# v1"),
        "prompts/a.yaml": "id: a\nname: 普通\n",
    }
    source = make_source("sample", files, branch="main", storage="disk")
    env = make_server(source)
    first = env.client.get("/sources/sample/docs/prompts/a.yaml")
    second = env.client.get("/sources/sample/docs/prompts/a.yaml")
    called = calls.read_text(encoding="utf-8").count("called")
    write_files(
        source.folder,
        {"scripts/convert_prompt.py": CONVERT_VERSION.format(calls=str(calls), heading="# v2")},
    )
    os.utime(source.folder / "scripts/convert_prompt.py", ns=(2_000_000_000, 2_000_000_000))
    # 実行
    third = env.client.get("/sources/sample/docs/prompts/a.yaml")
    # 検証
    assert first.status_code == 200
    assert first.json()["markdown"] == "# v1\n"
    assert second.json()["markdown"] == "# v1\n"
    assert called == 1
    assert third.status_code == 200
    assert third.json()["markdown"] == "# v2\n"

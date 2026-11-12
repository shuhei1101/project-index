from __future__ import annotations

import json
import logging
import shutil
import socket
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from project_index.features.admin.types import (
    CheckProjectRequest,
    FormatRequest,
    TryConvertRequest,
    WriteNavRequest,
)
from project_index.features.changes.types import ChangesRequest
from project_index.features.describe.types import DescribeRequest
from project_index.features.prompt_doc.runtime import DEFAULT_PROMPTS_DIR, PromptSet, load_prompts
from project_index.features.related.types import RelatedRequest
from project_index.features.search.types import MatchWordsRequest, SearchRequest
from project_index.features.write.types import DeleteRequest, WriteRequest
from project_index.server.app import build_app
from project_index.server.mcp.admin import NoArguments
from project_index.server.mcp.result import (
    DOCS_INSTRUCTIONS_PROMPT_ID,
    mcp_prompt_ids,
    tool_prompt_id,
)
from project_index.shared.yaml_io import load_yaml

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest
    from pydantic import BaseModel

BROKEN_CONFIG = "name: broken\ndocuments:\n  - id: sample\n    schema: schemas/sample.schema.yaml\n"
TOOL_NAMES = [
    "delete_docs",
    "describe",
    "list_changes",
    "list_match_words",
    "search_docs",
    "trace_related",
    "write_docs",
]
ADMIN_TOOL_NAMES = [
    "check_project",
    "reload",
    "restart",
    "status",
    "try_convert",
    "update",
    "write_nav",
]
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "integration-test", "version": "0"},
    },
}
LOCAL_CONFIG_ROWS = (
    "  - id: sample\n"
    "    paths: [alt/*.yaml]\n"
    "    schema: schemas/sample.schema.yaml\n"
    "  - id: extra\n"
    "    paths: [extra/*.yaml]\n"
    "    schema: schemas/sample.schema.yaml\n"
)
NO_SCRIPT_EXTRA = (
    "    converter: md\nconverters:\n  - id: md\n    run: [python3, scripts/missing.py]\n"
)
FILES_SCHEMA = Path(__file__).parents[3] / "templates" / "files.schema.yaml"
LISTEN_STATE = "0A"
TCP_TABLES = ("/proc/net/tcp", "/proc/net/tcp6")
LOOPBACK_V4 = "0100007F"
# どの文書にも当たらない `auto` の条件のタブ `none` を持つ nav
NONE_NAV = (
    "nav:\n"
    "  tabs:\n"
    "    - title: none\n"
    "      items:\n"
    "        - auto: {filter: {field: tags, op: eq, values: [none]}}\n"
)
# 文書の MCP の instructions の字数の上限
INSTRUCTIONS_MAX_CHARS = 4096
# instructions が持つ見出し（使用する場面・grep と Read が向く場面・ツールの順序・タグの付け方）
INSTRUCTIONS_HEADERS = ("使用する場面:", "grep・Read が向く場面:", "使用方法:", "タグ:")
# 文に置かない言い回し
FORBIDDEN_WORDS = ("MUST", "必ず", "禁止")
# 読み込み中の要求が答えないことを確かめる間と、読み終えた後に答えを待つ上限
LOADING_HOLD_SEC = 1
LOADING_REQUEST_SEC = 30
# ツールの名前 → 引数のスキーマの元の要求のモデル
DOCS_TOOL_MODELS: dict[str, type[BaseModel]] = {
    "search_docs": SearchRequest,
    "describe": DescribeRequest,
    "list_changes": ChangesRequest,
    "trace_related": RelatedRequest,
    "write_docs": WriteRequest,
    "delete_docs": DeleteRequest,
    "list_match_words": MatchWordsRequest,
}
ADMIN_TOOL_MODELS: dict[str, type[BaseModel]] = {
    "status": FormatRequest,
    "reload": FormatRequest,
    "restart": NoArguments,
    "update": NoArguments,
    "check_project": CheckProjectRequest,
    "try_convert": TryConvertRequest,
    "write_nav": WriteNavRequest,
}


def _kind_row(kind: str) -> str:
    """`sample` のスキーマで `{kind}/*.yaml` を読む文書の種類の行を作る。"""
    return f"  - id: {kind}\n    paths: [{kind}/*.yaml]\n    schema: schemas/sample.schema.yaml\n"


def _tool_data(result: dict[str, Any]) -> Any:
    """ツールの結果の本文を JSON として読む。"""
    return json.loads("".join(part["text"] for part in result["content"]))


def _listening_addresses(port: int) -> set[str]:
    """ポートで待ち受けているローカルアドレス（16 進）を /proc から集める。"""
    found: set[str] = set()
    for table in TCP_TABLES:
        for line in Path(table).read_text(encoding="utf-8").splitlines()[1:]:
            columns = line.split()
            address, local_port = columns[1].split(":")
            if columns[3] == LISTEN_STATE and int(local_port, 16) == port:
                found.add(address)
    return found


def _descriptions(response: httpx.Response) -> dict[str, str]:
    """`tools/list` の応答をツールの名前 → description にする。"""
    return {tool["name"]: tool["description"] for tool in response.json()["result"]["tools"]}


def _argument_keys(response: httpx.Response) -> dict[str, list[str]]:
    """`tools/list` の応答をツールの名前 → 引数のスキーマのキーにする。"""
    return {
        tool["name"]: sorted(tool["inputSchema"].get("properties", {}))
        for tool in response.json()["result"]["tools"]
    }


def _model_keys(models: dict[str, type[BaseModel]]) -> dict[str, list[str]]:
    """ツールの名前 → 要求のモデルのフィールド（別名があれば別名）にする。"""
    return {
        name: sorted(info.alias or key for key, info in model.model_fields.items())
        for name, model in models.items()
    }


def _rendered(prompts: PromptSet, server: str, names: dict[str, type[BaseModel]]) -> dict[str, str]:
    """プロンプトの YAML を描画した、ツールの名前 → description を返す。"""
    return {name: prompts.render(tool_prompt_id(server, name)) for name in names}


def _mcp(port: int, path: str, payload: dict[str, Any]) -> httpx.Response:
    """MCP の JSON-RPC を 1 つ送る。"""
    return httpx.post(
        f"http://127.0.0.1:{port}{path}", headers=MCP_HEADERS, json=payload, timeout=10
    )


def test_normal(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    start_serve: Callable[..., Any],
    wait_until_serving: Callable[..., None],
) -> None:
    """端末の設定の 2 つの配信元を配信し始める（正常系）。"""
    # 準備
    sample = make_source("sample")
    notes = make_source("notes", git=False)
    settings = write_settings(sample, notes)
    port = free_port()
    process = start_serve(settings, port)
    wait_until_serving(process, port)
    # 実行
    sample_docs = httpx.get(f"http://127.0.0.1:{port}/sources/sample/docs", timeout=10)
    notes_docs = httpx.get(f"http://127.0.0.1:{port}/sources/notes/docs", timeout=10)
    tools = _mcp(port, "/mcp/", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    admin = _mcp(port, "/_admin/mcp/", INITIALIZE)
    admin_tools = _mcp(port, "/_admin/mcp/", {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    session_start = httpx.post(
        f"http://127.0.0.1:{port}/_admin/session-start",
        json={"session_id": "s1", "reason": "startup"},
        timeout=10,
    )
    addresses = _listening_addresses(port)
    process.terminate()
    process.wait(timeout=15)
    output = process.stdout.read() if process.stdout else ""
    # 検証
    assert addresses == {LOOPBACK_V4}
    assert sample_docs.status_code == 200
    assert notes_docs.status_code == 200
    assert sorted(tool["name"] for tool in tools.json()["result"]["tools"]) == TOOL_NAMES
    assert admin.status_code == 200
    assert admin.json()["result"]["serverInfo"]
    assert (
        sorted(tool["name"] for tool in admin_tools.json()["result"]["tools"]) == ADMIN_TOOL_NAMES
    )
    assert session_start.status_code == 200
    assert session_start.json() == {"forgotten": False}
    assert f"http://127.0.0.1:{port}/" in output
    assert "sample" in output
    assert "notes" in output


def test_normal_when_mcp_path_without_slash(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    start_serve: Callable[..., Any],
    wait_until_serving: Callable[..., None],
) -> None:
    """スラッシュ無しの /mcp・/_admin/mcp への POST に、リダイレクトを挟まずに MCP が応える（正常系）。"""
    # 準備
    settings = write_settings(make_source("sample"))
    port = free_port()
    process = start_serve(settings, port)
    wait_until_serving(process, port)
    # 実行
    docs = _mcp(port, "/mcp", INITIALIZE)
    admin = _mcp(port, "/_admin/mcp", INITIALIZE)
    docs_slash = _mcp(port, "/mcp/", INITIALIZE)
    admin_slash = _mcp(port, "/_admin/mcp/", INITIALIZE)
    process.terminate()
    process.wait(timeout=15)
    # 検証
    assert docs.status_code == 200
    assert docs.json()["result"]["serverInfo"]
    assert admin.status_code == 200
    assert admin.json()["result"]["serverInfo"]
    assert docs_slash.status_code == 200
    assert admin_slash.status_code == 200


def test_normal_when_configs_merged(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """config の複数の YAML を上から順にマージする（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(description="基本の説明"),
            "project-index.local.yaml": (
                "name: sample\ndescription: 上書きの説明\ndocuments:\n" + LOCAL_CONFIG_ROWS
            ),
            "alt/doc-9.yaml": "id: doc-9\nname: 別の置き場の文書\n",
            "extra/doc-x.yaml": "id: doc-x\nname: 追加した行の文書\n",
        }
    )
    source = make_source(
        "sample", files, config_names=("project-index.yaml", "project-index.local.yaml")
    )
    env = make_server(source)
    # 実行
    described = env.call("describe", cwd=str(source.folder))
    overridden = env.call(
        "search_docs",
        cwd=str(source.folder),
        filter={"field": "kind", "op": "eq", "values": ["sample"]},
        view="ids",
        format="json",
    )
    added = env.call(
        "search_docs",
        cwd=str(source.folder),
        filter={"field": "kind", "op": "eq", "values": ["extra"]},
        view="ids",
        format="json",
    )
    # 検証
    assert "上書きの説明" in described.text
    assert "基本の説明" not in described.text
    assert [item["id"] for item in overridden.data["items"]] == ["doc-9"]
    assert [item["id"] for item in added.data["items"]] == ["doc-x"]


def test_normal_when_config_version_old(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """古いバージョンの設定の配信元も配信し、警告を残す（正常系）。"""
    # 準備
    config = sample_config_text(name="old", version="0")
    old = make_source("old", sample_file_set(**{"project-index.yaml": config}))
    caplog.set_level(logging.WARNING)
    # 実行
    env = make_server(old)
    response = env.client.get("/sources/old/docs")
    # 検証
    warnings = [record.getMessage() for record in caplog.records if "old" in record.getMessage()]
    assert response.status_code == 200
    assert any("0" in message and "3" in message for message in warnings)


def test_normal_when_source_invalid(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """設定がスキーマに違反する配信元と、スクリプトを実行できない配信元を外して配信する（正常系）。"""
    # 準備
    sample = make_source("sample")
    broken = make_source("broken", {"project-index.yaml": BROKEN_CONFIG})
    noscript_config = sample_config_text(NO_SCRIPT_EXTRA, name="noscript")
    noscript = make_source("noscript", sample_file_set(**{"project-index.yaml": noscript_config}))
    caplog.set_level(logging.ERROR)
    # 実行
    env = make_server(sample, broken, noscript)
    # 検証
    logs = caplog.text
    assert env.client.get("/sources/broken/docs").status_code == 404
    assert env.client.get("/sources/noscript/docs").status_code == 404
    assert env.client.get("/sources/sample/docs").status_code == 200
    assert env.call("describe", cwd=str(sample.folder)).is_error is False
    assert "broken: documents[0].paths: 必須のキーが無い" in logs
    assert "noscript: converters[0]" in logs
    assert "scripts/missing.py" in logs
    assert env.client.post("/_admin/mcp/", headers=MCP_HEADERS, json=INITIALIZE).status_code == 200


def test_normal_when_schema_from_other_source(
    make_source: Callable[..., Any],
    make_schemas_source: Callable[..., Any],
    make_server: Callable[..., Any],
    ref_config_text: Callable[..., str],
) -> None:
    """参照先の配信元が検証で外れていても、ほかの配信元のリビジョンのスキーマで参照する側の配信元を組み立てる（正常系）。"""
    # 準備
    schemas = make_schemas_source({}, config="name: schemas\ndocuments:\n  - id: note\n")
    sample = make_source(
        "sample",
        {
            "project-index.yaml": ref_config_text(
                "sample",
                [{"source": "schemas", "path": "schemas/note.schema.yaml", "ref": "v1"}],
            ),
            "notes/a.yaml": "id: a\nname: A\n",
        },
        git=False,
    )
    # 実行
    env = make_server(sample, schemas)
    # 検証
    assert env.client.get("/sources/sample/docs").status_code == 200
    assert env.client.get("/sources/schemas/docs").status_code == 404
    result = env.call(
        "describe", cwd=str(sample.folder), source="sample", kind="note", format="json"
    )
    assert result.data["schema"]["title"] == "note"


def test_normal_when_metadata_out_of_sync(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """metadata の列の欠けと管理用の YAML のずれがあっても配信し、件数を警告のログに残す（正常系）。"""
    # 準備
    rows = (
        "    metadata:\n"
        "      name: title\n"
        "  - id: src\n"
        "    paths: [src/files.yaml]\n"
        "    schema: schemas/files.schema.yaml\n"
        "    records: files\n"
        "    body_file: path\n"
    )
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(rows),
            "schemas/files.schema.yaml": FILES_SCHEMA.read_text(encoding="utf-8"),
            "docs/doc-1.yaml": "id: doc-1\nname: 文書 1\ntitle: 文書 1\n",
            "docs/doc-2.yaml": "id: doc-2\nname: 文書 2\n",
            "src/files.yaml": (
                "files:\n"
                "  - path: a.py\n"
                "    related:\n"
                "      - {to: src/z.py, type: tests}\n"
                "  - path: c.py\n"
            ),
            "src/a.py": "a = 1\n",
            "src/d.py": "d = 4\n",
            "src/sub/e.py": "e = 5\n",
        }
    )
    sample = make_source("sample", files)
    clean = make_source(
        "clean", sample_file_set(**{"project-index.yaml": sample_config_text(name="clean")})
    )
    caplog.set_level(logging.WARNING)
    # 実行
    env = make_server(sample, clean)
    # 検証
    warnings = [record.getMessage() for record in caplog.records]
    sample_warnings = [message for message in warnings if message.startswith("sample:")]
    assert env.client.get("/sources/sample/docs").status_code == 200
    assert len(sample_warnings) == 4
    assert any("metadata の列の欠け 1 件" in m and "name（title）" in m for m in sample_warnings)
    assert any(
        "管理用の YAML に無いファイル 2 件" in m and "src/d.py" in m and "src/sub/e.py" in m
        for m in sample_warnings
    )
    assert any("ファイルが無い行 1 件" in m and "c.py" in m for m in sample_warnings)
    assert any(
        "どの文書にも該当しない関連 1 件" in m and "src: src/a.py: src/z.py" in m
        for m in sample_warnings
    )
    assert not any("src: src/files.yaml" in m for m in sample_warnings)
    assert [message for message in warnings if message.startswith("clean:")] == []


def test_normal_when_source_config_legacy(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """前の形式の配信元を外して配信し、違反と移し替えの案内をエラーログに残す（正常系）。"""
    # 準備
    sample = make_source("sample")
    legacy_config = (
        'version: "1"\n'
        "name: legacy\n"
        "tags: tags.yaml\n"
        "documents:\n"
        "  - id: notes\n"
        "    paths: [docs/*.md]\n"
        "    schema: schemas/sample.schema.yaml\n"
        "    type: markdown\n"
        "  - id: rules\n"
        "    paths: [docs/*.yaml]\n"
        "    schema: schemas/sample.schema.yaml\n"
        "    type: yaml\n"
        "    metadata:\n"
        "      name: {type: ref, field: title}\n"
        "    defaults:\n"
        "      - paths: [docs/**]\n"
        "        tags: [doc]\n"
    )
    legacy = make_source(
        "legacy", {"project-index.yaml": legacy_config, "tags.yaml": "python: Python の規約\n"}
    )
    caplog.set_level(logging.ERROR)
    # 実行
    env = make_server(sample, legacy)
    # 検証
    logs = caplog.text
    assert env.client.get("/sources/legacy/docs").status_code == 404
    assert env.client.get("/sources/sample/docs").status_code == 200
    assert "legacy: tags" in logs
    assert "legacy: documents[0].type" in logs
    assert "legacy: documents[1].type" in logs
    assert "legacy: documents[1].defaults" in logs
    assert "legacy: documents[1].metadata.name" in logs
    assert "project-index migrate --source" in logs


def test_error_when_terminal_config_invalid(
    tmp_path: Path,
    free_port: Callable[[], int],
    start_serve: Callable[..., Any],
) -> None:
    """端末の設定がスキーマに違反すると待ち受けずに終わる（異常系）。"""
    # 準備
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        'version: "1"\nclone: /tmp/clone\nport: "not-a-number"\nsources:\n  - id: a\n    enable: false\n',
        encoding="utf-8",
    )
    port = free_port()
    # 実行
    invalid = start_serve(settings, port)
    invalid_code = invalid.wait(timeout=30)
    invalid_error = invalid.stderr.read() if invalid.stderr else ""
    missing_file = tmp_path / "no-such-settings.yaml"
    missing = start_serve(missing_file, port)
    missing_code = missing.wait(timeout=30)
    missing_error = missing.stderr.read() if missing.stderr else ""
    # 検証
    assert invalid_code == 2
    assert f"{settings}: sources[0].config" in invalid_error
    assert f"{settings}: port" in invalid_error
    assert f"{settings}: sources[0].enable" in invalid_error
    assert missing_code == 2
    assert str(missing_file) in missing_error
    assert _listening_addresses(port) == set()


def test_error_when_port_in_use(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    start_serve: Callable[..., Any],
) -> None:
    """ポートで待ち受けられないと終わる（異常系）。"""
    # 準備
    settings = write_settings(make_source("sample"))
    port = free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", port))
        occupied.listen()
        # 実行
        process = start_serve(settings, port)
        code = process.wait(timeout=30)
        error = process.stderr.read() if process.stderr else ""
    # 検証
    assert code == 3
    assert str(port) in error
    assert "PROJECT_INDEX_PORT" in error


def test_normal_when_config_read_from_default_ref(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    start_serve: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    call_tool: Callable[..., dict[str, Any]],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """クローン本体が別のブランチでも、default_ref の設定とスキーマで配信元を組み立てる（正常系）。"""
    # 準備
    sample = make_source("sample")
    run_git(sample.folder, "branch", "master")
    commit_all(sample.folder, {"project-index.yaml": sample_config_text(_kind_row("kind_a"))})
    run_git(sample.folder, "checkout", "master")
    worktree = sample.folder / ".claude" / "worktrees" / "develop"
    run_git(sample.folder, "worktree", "add", str(worktree), "develop")
    notes_files = sample_file_set(
        **{"project-index.yaml": sample_config_text(_kind_row("kind_n"), name="notes")}
    )
    notes = make_source("notes", notes_files, git=False, scope_read=[sample.folder])
    port = free_port()
    process = start_serve(write_settings(sample, notes), port)
    wait_until_serving(process, port)
    cwd = str(sample.folder)
    # 実行
    with httpx.Client(timeout=15) as client:
        first = _tool_data(
            call_tool(client, port, "/mcp/", "describe", cwd=cwd, source="sample", format="json")
        )
        commit_all(
            worktree,
            {"project-index.yaml": sample_config_text(_kind_row("kind_a") + _kind_row("kind_b"))},
        )
        second = _tool_data(
            call_tool(client, port, "/mcp/", "describe", cwd=cwd, source="sample", format="json")
        )
        disk = _tool_data(
            call_tool(client, port, "/mcp/", "describe", cwd=cwd, source="notes", format="json")
        )
    # 検証
    assert "kind_a" in {kind["id"] for kind in first["kinds"]}
    assert {"kind_a", "kind_b"} <= {kind["id"] for kind in second["kinds"]}
    assert str(worktree) in {item["path"] for item in first["worktrees"]}
    assert "kind_n" in {kind["id"] for kind in disk["kinds"]}


def test_normal_when_alias_and_nav_warned(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    start_serve: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    call_tool: Callable[..., dict[str, Any]],
    alias_file_set: Callable[..., dict[str, str]],
) -> None:
    """エイリアスのキーの違反と 0 件に当たる nav の条件を警告のログに出し、配信を始める（正常系）。"""
    # 準備
    sample = make_source("sample", alias_file_set(NONE_NAV, broken=True))
    port = free_port()
    process = start_serve(write_settings(sample), port)
    wait_until_serving(process, port)
    cwd = str(sample.folder)
    # 実行
    with httpx.Client(timeout=15) as client:
        status = call_tool(client, port, "/_admin/mcp/", "status", format="json")
        found = _tool_data(
            call_tool(
                client, port, "/mcp/", "search_docs", cwd=cwd, term="壊れた用語", format="json"
            )
        )
        words = _tool_data(
            call_tool(
                client, port, "/mcp/", "list_match_words", source="sample", cwd=cwd, format="json"
            )
        )
    process.terminate()
    process.wait(timeout=15)
    logs = process.stderr.read() if process.stderr else ""
    # 検証
    assert "terms/broken.yaml" in logs
    assert "文字列か文字列の並び" in logs
    assert "none" in logs
    sources = {item["id"]: item for item in status["structuredContent"]["sources"]}
    assert sources["sample"]["status"] == "serving"
    assert not found.get("items")
    assert "壊れた用語" not in {item["word"] for item in words["words"]}


def test_normal_when_mcp_text_from_prompts(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    start_serve: Callable[..., Any],
    wait_until_serving: Callable[..., None],
) -> None:
    """文書の MCP の instructions と 2 つの MCP のツールの description をプロンプトの YAML から描画して返す（正常系）。"""
    # 準備
    port = free_port()
    process = start_serve(write_settings(make_source("sample")), port)
    wait_until_serving(process, port)
    prompts = load_prompts(DEFAULT_PROMPTS_DIR, required=mcp_prompt_ids())
    # 実行
    initialized = _mcp(port, "/mcp/", INITIALIZE)
    tools = _mcp(port, "/mcp/", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    admin_tools = _mcp(port, "/_admin/mcp/", {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    process.terminate()
    process.wait(timeout=15)
    # 検証
    instructions = initialized.json()["result"]["instructions"]
    texts = [instructions, *_descriptions(tools).values(), *_descriptions(admin_tools).values()]
    assert instructions == prompts.render(DOCS_INSTRUCTIONS_PROMPT_ID)
    assert [header for header in INSTRUCTIONS_HEADERS if header not in instructions] == []
    assert len(instructions) <= INSTRUCTIONS_MAX_CHARS
    assert _descriptions(tools) == _rendered(prompts, "docs", DOCS_TOOL_MODELS)
    assert _descriptions(admin_tools) == _rendered(prompts, "admin", ADMIN_TOOL_MODELS)
    assert [text for text in texts if any(word in text for word in FORBIDDEN_WORDS)] == []
    assert _argument_keys(tools) == _model_keys(DOCS_TOOL_MODELS)
    assert _argument_keys(admin_tools) == _model_keys(ADMIN_TOOL_MODELS)


def test_error_when_prompt_invalid(
    tmp_path: Path,
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    start_serve: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """プロンプトの YAML がスキーマに違反すると待ち受けずに終わる（異常系）。"""
    # 準備
    prompts = tmp_path / "prompts"
    shutil.copytree(DEFAULT_PROMPTS_DIR, prompts)
    broken = prompts / "mcp" / "docs" / "tools" / "search-docs.yaml"
    value = load_yaml(broken.read_text(encoding="utf-8"))
    del value["kind"]
    broken.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("PROJECT_INDEX_PROMPTS_DIR", str(prompts))
    settings = write_settings(make_source("sample"))
    port = free_port()
    # 実行
    process = start_serve(settings, port)
    code = process.wait(timeout=30)
    error = process.stderr.read() if process.stderr else ""
    # 検証
    assert code == 4
    assert _listening_addresses(port) == set()
    assert str(broken) in error
    assert "kind" in error


def test_normal_when_requested_while_loading(
    make_source: Callable[..., Any],
    make_loading_server: Callable[..., Any],
    serve_in_thread: Callable[[Any, int], None],
    free_port: Callable[[], int],
) -> None:
    """配信元を読む前に待ち受け、読む間に届いた要求は読み終えてから答える（正常系）。"""
    # 準備
    loading = make_loading_server(make_source("sample"))
    port = free_port()
    serve_in_thread(build_app(loading.env.handlers), port)
    responses: dict[str, httpx.Response] = {}

    def request_docs() -> None:
        responses["docs"] = httpx.get(
            f"http://127.0.0.1:{port}/sources/sample/docs", timeout=LOADING_REQUEST_SEC
        )

    # 実行
    with socket.create_connection(("127.0.0.1", port), timeout=5):
        connected = True
    docs_thread = threading.Thread(target=request_docs)
    docs_thread.start()
    docs_thread.join(timeout=LOADING_HOLD_SEC)
    answered_before = "docs" in responses
    loading.finish()
    docs_thread.join(timeout=LOADING_REQUEST_SEC)
    # 検証
    assert connected
    assert answered_before is False
    assert responses["docs"].status_code == 200
    assert [item["id"] for item in responses["docs"].json()["documents"]] == ["doc-1", "doc-2"]


def test_normal_when_other_source_loading(
    make_source: Callable[..., Any], make_loading_server: Callable[..., Any]
) -> None:
    """読み込み済みの配信元への要求は、他の配信元の読み込みを待たない（正常系）。"""
    # 準備
    sample = make_source("sample")
    notes = make_source("notes")
    loading = make_loading_server(sample, notes, blocked=("notes",))
    env = loading.env
    results: dict[str, Any] = {}

    def search_notes() -> None:
        results["notes"] = env.call("search_docs", cwd=str(notes.folder), source="notes")

    # 実行
    found = env.call("search_docs", cwd=str(sample.folder), source="sample", view="ids")
    docs = env.client.get("/sources/sample/docs")
    notes_thread = threading.Thread(target=search_notes)
    notes_thread.start()
    notes_thread.join(timeout=LOADING_HOLD_SEC)
    answered_before = "notes" in results
    status = env.call_admin("status", format="json")
    loading.finish()
    notes_thread.join(timeout=LOADING_REQUEST_SEC)
    # 検証
    assert not found.is_error
    assert "doc-1" in found.text
    assert docs.status_code == 200
    assert answered_before is False
    assert status.data["loading"] is True
    assert not results["notes"].is_error
    assert results["notes"].text.startswith("notes: ")


def test_normal_when_requested_source_loaded_first(
    make_source: Callable[..., Any], make_loading_server: Callable[..., Any]
) -> None:
    """待っている要求が指す配信元を、端末の設定の順より先に読み込む（正常系）。"""
    # 準備
    a, b, c = (make_source(source_id) for source_id in ("a", "b", "c"))
    loading = make_loading_server(a, b, c, blocked=("a",), held=("b",))
    env = loading.env
    results: dict[str, Any] = {}

    def search_c() -> None:
        results["c"] = env.call("search_docs", cwd=str(c.folder), source="c")
        # c の答えが届いた時点で読み込みを終えていた配信元
        results["loaded"] = list(loading.loaded)

    # 実行
    c_thread = threading.Thread(target=search_c)
    c_thread.start()
    received = loading.waiting.wait(timeout=LOADING_REQUEST_SEC)
    loading.release.set()
    c_thread.join(timeout=LOADING_REQUEST_SEC)
    loading.finish()
    # 検証
    assert received
    assert loading.order == ["a", "c", "b"]
    assert not results["c"].is_error
    assert results["c"].text.startswith("c: ")
    assert results["loaded"] == ["a", "c"]


def test_error_when_source_load_failed(
    make_source: Callable[..., Any],
    make_loading_server: Callable[..., Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """読み込みが例外で止まった行を配信せず、残りの行を読み込み続ける（異常系）。"""
    # 準備
    broken = make_source("broken")
    sample = make_source("sample")
    caplog.set_level(logging.ERROR)
    loading = make_loading_server(broken, sample, blocked=(), failing=("broken",))
    env = loading.env
    # 実行
    failed = env.call("search_docs", cwd=str(broken.folder), source="broken")
    found = env.call("search_docs", cwd=str(sample.folder), source="sample", view="ids")
    loading.thread.join(timeout=LOADING_REQUEST_SEC)
    status = env.call_admin("status", format="json")
    # 検証
    sources = {item["id"]: item for item in status.data["sources"]}
    assert failed.is_error
    assert "SourceNotServedError" in failed.text
    assert not found.is_error
    assert "doc-1" in found.text
    assert status.data["loading"] is False
    assert sources["broken"]["status"] == "not_served"
    assert any("sources[0]" in error for error in sources["broken"]["errors"])
    assert any("broken を読み込めない" in error for error in sources["broken"]["errors"])
    assert sources["sample"]["status"] == "serving"
    assert "broken を読み込めない" in caplog.text


IGNORED_KIND_ROW = "  - id: kind_a\n    paths: [kind_a/*.yaml]\n    schema: schemas/a.schema.yaml\n"


def test_normal_when_ignored_config_first(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """先頭の設定が default_ref に無く .gitignore で無視されていれば、設定をディスクから、スキーマを default_ref から読む（正常系）。"""
    # 準備
    files = {k: v for k, v in sample_file_set().items() if k != "project-index.yaml"}
    files[".gitignore"] = "project-index.local.yaml\n"
    sample = make_source("sample", files, config_names=("project-index.local.yaml",))
    run_git(sample.folder, "branch", "master")
    schema = (sample.folder / "schemas" / "sample.schema.yaml").read_text(encoding="utf-8")
    commit_all(sample.folder, {"schemas/a.schema.yaml": schema})
    run_git(sample.folder, "checkout", "master")
    local = sample.folder / "project-index.local.yaml"
    local.write_text(sample_config_text(IGNORED_KIND_ROW), encoding="utf-8")
    # 実行
    env = make_server(sample)
    result = env.call("describe", cwd=str(sample.folder), source="sample", format="json")
    # 検証
    assert result.is_error is False
    data = result.data
    assert "kind_a" in {kind["id"] for kind in data["kinds"]}
    assert not (sample.folder / "schemas" / "a.schema.yaml").exists()
    assert env.handlers.registry.get("sample").root == sample.folder


def test_normal_when_first_config_not_committed(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """.gitignore していない先頭の設定が default_ref に無い配信元を外して配信する（正常系）。"""
    # 準備
    sample = make_source("sample")
    files = {k: v for k, v in sample_file_set().items() if k != "project-index.yaml"}
    uncommitted = make_source("uncommitted", files)
    (uncommitted.folder / "project-index.yaml").write_text(
        sample_config_text(name="uncommitted"), encoding="utf-8"
    )
    caplog.set_level(logging.ERROR)
    # 実行
    env = make_server(sample, uncommitted)
    # 検証
    assert env.client.get("/sources/uncommitted/docs").status_code == 404
    assert env.client.get("/sources/sample/docs").status_code == 200
    assert "uncommitted: config[0]: develop に project-index.yaml がありません" in caplog.text


def test_normal_when_xdg_dirs_set(
    make_source: Callable[..., Any],
    free_port: Callable[[], int],
    start_serve: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    tmp_path: Path,
) -> None:
    """PROJECT_INDEX_CONFIG が無ければ XDG_CONFIG_HOME の下の端末の設定を読み、状態とログを決めた置き場に書く（正常系）。"""
    # 準備
    sample = make_source("sample")
    config_home = tmp_path / "xdg-config"
    state_home = tmp_path / "xdg-state"
    override = tmp_path / "override"
    configured = tmp_path / "configured"
    home = tmp_path / "home"
    settings = config_home / "project-index" / "settings.yaml"
    settings.parent.mkdir(parents=True)
    base = (
        'version: "1"\n'
        f"clone: {tmp_path / 'clone'}\n"
        "sources:\n"
        "  - id: sample\n"
        f"    config: [{sample.config[0]}]\n"
        f"    scope: {{read: [{sample.folder}]}}\n"
    )
    env = {
        "XDG_CONFIG_HOME": str(config_home),
        "XDG_STATE_HOME": str(state_home),
        "HOME": str(home),
    }

    def serve_once(extra_env: dict[str, str]) -> int:
        port = free_port()
        process = start_serve(None, port, extra_env={**env, **extra_env})
        wait_until_serving(process, port)
        code = httpx.get(f"http://127.0.0.1:{port}/sources/sample/docs", timeout=30).status_code
        process.terminate()
        process.wait(timeout=15)
        return code

    # 実行
    settings.write_text(base, encoding="utf-8")
    first = serve_once({})
    first_log = (state_home / "project-index" / "logs" / "project-index.log").is_file()
    shutil.rmtree(state_home)
    settings.write_text(base + f"state_dir: {configured}\n", encoding="utf-8")
    second = serve_once({"PROJECT_INDEX_STATE_DIR": str(override)})
    settings.write_text(base, encoding="utf-8")
    third = serve_once({"XDG_STATE_HOME": "rel"})
    # 検証
    assert first == 200
    assert first_log
    assert second == 200
    assert (override / "logs" / "project-index.log").is_file()
    assert not configured.exists()
    assert third == 200
    assert (home / ".local" / "state" / "project-index" / "logs" / "project-index.log").is_file()
    assert not (Path.cwd() / "rel").exists()
    assert not state_home.exists()


BRAIN_CONFIG = (
    "name: brain\n"
    "paths_base: ../../..\n"
    "documents:\n"
    "  - id: note\n"
    "    paths: [docs/knowhow/*.yaml, content/node-docs/shared/*.yaml]\n"
    "    schema: note.schema.yaml\n"
)


def test_normal_when_paths_base_set(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
) -> None:
    """paths_base を持つ配信元を、paths を基準のフォルダから解いて配信し、スキーマは設定ファイルのフォルダから解く（正常系）。"""
    # 準備
    files = {
        "content/node-docs/brain/project-index.yaml": BRAIN_CONFIG,
        "content/node-docs/brain/note.schema.yaml": "title: note\ntype: object\n",
        "docs/knowhow/a.yaml": "id: a\nname: ノウハウ A\n",
        "content/node-docs/shared/b.yaml": "id: b\nname: 共有 B\n",
        "docs/design/c.yaml": "id: c\nname: 設計 C\n",
    }
    brain = make_source(
        "brain", files, config_names=("content/node-docs/brain/project-index.yaml",)
    )
    env = make_server(brain)
    cwd = str(brain.folder / "content" / "node-docs" / "brain")
    # 実行
    found = env.call("search_docs", cwd=cwd, source="brain", format="json")
    listed = env.client.get("/sources/brain/docs")
    schema = env.call("describe", cwd=cwd, source="brain", kind="note", format="json")
    # 検証
    assert sorted(item["id"] for item in found.data["items"]) == ["a", "b"]
    assert sorted(row["path"] for row in listed.json()["documents"]) == [
        "content/node-docs/shared/b.yaml",
        "docs/knowhow/a.yaml",
    ]
    assert schema.data["schema"]["title"] == "note"


def test_normal_when_terminal_config_has_unknown_top_level_key(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    start_serve: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    call_tool: Callable[..., dict[str, Any]],
) -> None:
    """端末の設定の最上位の知らないキーを違反にせず、警告のログと引数なしの describe の警告に残して配信を始める（正常系）。"""
    # 準備
    sample = make_source("sample")
    settings = write_settings(sample, extra="mindstella:\n  threads: 3\nprot: 9000")
    port = free_port()
    process = start_serve(settings, port)
    wait_until_serving(process, port)
    # 実行
    with httpx.Client(timeout=15) as client:
        docs = client.get(f"http://127.0.0.1:{port}/sources/sample/docs")
        described = _tool_data(
            call_tool(client, port, "/mcp/", "describe", cwd=str(sample.folder), format="json")
        )
    process.terminate()
    process.wait(timeout=15)
    logs = process.stderr.read() if process.stderr else ""
    # 検証
    assert docs.status_code == 200
    assert str(settings) in logs
    assert "mindstella, prot" in logs
    unknown = [w for w in described["warnings"] if "mindstella" in w]
    assert len(unknown) == 1
    assert "prot" in unknown[0]

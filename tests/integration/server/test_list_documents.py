from __future__ import annotations

import math
import threading
import time
from typing import TYPE_CHECKING, Any, cast

from ruamel.yaml import YAML

from project_index.features.documents import store as store_module
from project_index.features.documents.store import check_sync
from project_index.features.read import route as route_module
from project_index.features.settings.query import load_terminal_config
from project_index.features.sources import service as sources_service_module
from project_index.features.sources.service import load_source, validate_source_config
from project_index.main import build_handlers
from project_index.shared.yaml_io import load_yaml
from tests.integration.server.conftest import BACKGROUND_WAIT_SEC, FILES_SCHEMA_TEMPLATE

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

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
    """種類 `design` の YAML 2 件（1 件目だけが `visibility` を持つ）と、管理用の YAML の行の文書 1 件を持つ配信元のファイル一式を返す。"""
    return {
        "project-index.yaml": CONFIG,
        "schemas/design.schema.yaml": DESIGN_SCHEMA,
        "schemas/common.schema.yaml": COMMON_SCHEMA,
        "schemas/files.schema.yaml": FILES_SCHEMA_TEMPLATE.read_text(encoding="utf-8"),
        "design/D-1.yaml": "id: D-1\nname: 設計 1\ndescription: 1 件目\ntags: [a]\ntitle: 最初\nvisibility: internal\n",
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
        "visibility": "internal",
        "bodyPath": None,
        "version": first["version"],
        "value": None,
        "commonKeys": None,
    }
    assert isinstance(first["version"], str)
    assert first["version"]
    assert body["documents"][2]["bodyPath"] == "notes/guide.md"
    # visibility を持たない文書は null
    assert body["documents"][1]["visibility"] is None


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


def test_normal_when_common_keys_requested(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """`common_keys` を指したときだけ、各文書の共通のキーを返す（正常系）。"""
    # 準備（種類 design の行に、name を title から・related を links から取る対応と alias_type を持たせる）
    files = main_files()
    files["project-index.yaml"] = CONFIG.replace(
        "    schema: schemas/design.schema.yaml\n",
        "    schema: schemas/design.schema.yaml\n"
        "    metadata:\n"
        "      name: title\n"
        "      related: links\n"
        "    alias_type: term\n",
    )
    files["design/D-1.yaml"] += "links:\n  - to: D-2\n"
    env = make_server(make_source("sample", files, branch="main"))
    # 実行
    response = env.client.get("/sources/sample/docs", params={"common_keys": "true"})
    omitted = env.client.get("/sources/sample/docs")
    # 検証
    documents = response.json()["documents"]
    assert response.status_code == 200
    common_keys = documents[0]["commonKeys"]
    assert common_keys["name"] == "最初"
    assert common_keys["related"] == [{"to": "D-2"}]
    assert common_keys["alias_type"] == "term"
    assert common_keys["visibility"] == "internal"
    # 中のキーは METADATA_KEYS の名前のまま（camelCase にしない）で、値の無いキーを持たない
    assert "aliasType" not in common_keys
    assert None not in common_keys.values()
    assert all(row["commonKeys"] is None for row in omitted.json()["documents"])


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


def test_normal_when_revision_export_times_out(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    time_out_archive: Callable[..., list[str]],
) -> None:
    """文書の一覧はリビジョンを書き出さずに commit の blob を読み込むため、書き出しが上限を超える commit でも一覧を返す（正常系）。"""
    # 準備
    source = make_source("sample", main_files(), branch="main")
    parent = run_git(source.folder, "rev-parse", "HEAD").strip()
    commit_all(source.folder, {"design/D-3.yaml": "id: D-3\nname: 設計 3\n"}, "docs: 追加")
    failed = time_out_archive(commits={parent})
    env = make_server(source)
    env.wait_background()
    # 実行
    response = env.client.get("/sources/sample/docs", params={"ref": parent})
    # 検証
    body = response.json()
    assert response.status_code == 200
    assert [(row["kind"], row["path"]) for row in body["documents"]] == [
        ("design", "design/D-1.yaml"),
        ("design", "design/D-2.yaml"),
        ("notes", "notes/files.yaml"),
    ]
    assert failed == []
    assert list((env.state_dir / "snapshots").glob(f"*/{parent}")) == []


def test_normal_when_disk_storage(
    make_local_source: Callable[..., Any],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """disk の配信元は ref を無視して登録したフォルダの文書を返す（正常系）。"""
    # 準備
    company = make_local_source()
    run_git(company.folder, "branch", "master")
    env = make_server(company)
    # 実行
    response = env.client.get("/sources/company/docs", params={"ref": "master"})
    # 検証
    body = response.json()
    assert response.status_code == 200
    assert body["ref"] == ""
    assert [(row["path"], row["bodyPath"]) for row in body["documents"]] == [
        ("files.local.yaml", "src/app.py")
    ]


# 裏の検査が始まってから、文書の一覧の応答を返させる合図を出すまでの秒数
SIGNAL_AFTER_SEC = 1.0
# 1 件あたりの時間を測る配信元の文書の数
CALIBRATION_COUNT = 200
# 裏の検査のスレッドの名前
CHECK_THREAD = "project-index-source-checks"


def large_files(count: int) -> dict[str, str]:
    """種類 `design` の YAML を `count` 件持つ配信元のファイル一式を返す。"""
    files = {
        "project-index.yaml": (
            "name: large\n"
            "documents:\n"
            "  - id: design\n"
            "    paths: [design/*.yaml]\n"
            "    schema: schemas/design.schema.yaml\n"
        ),
        "schemas/design.schema.yaml": DESIGN_SCHEMA,
        "schemas/common.schema.yaml": COMMON_SCHEMA,
    }
    for number in range(count):
        files[f"design/D-{number}.yaml"] = (
            f"id: D-{number}\nname: 設計 {number}\ntags: [a, b]\ntitle: {number} 件目\n"
        )
    return files


def _check_seconds_per_file(
    make_source: Callable[..., Any], write_settings: Callable[..., Path]
) -> float:
    """休まない検査の、同じ形の文書 1 件あたりの秒数を測る。"""
    spec = make_source("calibration", large_files(CALIBRATION_COUNT), git=False)
    terminal = load_terminal_config(write_settings(spec, name="calibration.yaml"))
    handlers = build_handlers(terminal)
    handlers.registry.load(terminal)
    [source] = handlers.registry.served()
    # 要求のスレッドで流すため、関所は休まない
    started = time.perf_counter()
    check_sync(handlers.store, source)
    return (time.perf_counter() - started) / CALIBRATION_COUNT


def _wait_exported(env: Any) -> None:
    """裏のリビジョンの書き出しが済むまで待つ（裏の検査は待たない）。"""
    deadline = time.monotonic() + BACKGROUND_WAIT_SEC
    while env.handlers.snapshots.exporting and time.monotonic() < deadline:
        time.sleep(0.01)


def test_normal_when_background_check_running(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    write_settings: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """応答の最中は、裏の検査が休みを挟んで進む（正常系）。"""
    # 準備
    per_file = _check_seconds_per_file(make_source, write_settings)
    # 合図までの 1 秒に 1 割の速さで読む分を引いても、合図の後に 1 秒以上残る件数
    count = math.ceil(2 * SIGNAL_AFTER_SEC / per_file)
    large = make_source("large", large_files(count), git=False)
    entered = threading.Event()
    release = threading.Event()
    reads: list[float] = []
    real_list_documents = route_module.list_documents
    real_load_file = store_module.load_file

    def held_list_documents(target: Any, **kwargs: Any) -> Any:
        # sample の一覧だけを、合図まで応答の最中に保つ
        if target.source.id == "sample":
            entered.set()
            release.wait(timeout=BACKGROUND_WAIT_SEC)
        return real_list_documents(target, **kwargs)

    def recorded_load_file(root: Path, path: str, table: Any, **kwargs: Any) -> Any:
        # 裏の検査が large の文書のファイルを読み込んだ時刻を記録する
        if threading.current_thread().name == CHECK_THREAD and kwargs["source_id"] == "large":
            reads.append(time.perf_counter())
        return real_load_file(root, path, table, **kwargs)

    monkeypatch.setattr(route_module, "list_documents", held_list_documents)
    monkeypatch.setattr(store_module, "load_file", recorded_load_file)
    # large を先に並べ、起動の直後の裏の検査で先に検査させる
    env = make_server(large, make_source("sample", main_files(), branch="main"))
    # sample の default_ref の裏の書き出しを済ませ、応答の最中に休むのを裏の検査だけにする
    _wait_exported(env)
    responses: list[Any] = []
    request = threading.Thread(
        target=lambda: responses.append(env.client.get("/sources/sample/docs"))
    )
    # 実行
    request.start()
    reached = entered.wait(timeout=BACKGROUND_WAIT_SEC)
    held_from = time.perf_counter()
    time.sleep(max(0.0, (reads[0] if reads else held_from) + SIGNAL_AFTER_SEC - held_from))
    released_at = time.perf_counter()
    release.set()
    request.join(timeout=BACKGROUND_WAIT_SEC)
    env.wait_background()
    # 検証
    held = [at for at in reads if held_from <= at <= released_at]
    after = [at for at in reads if at > released_at]
    checked = env.handlers.checks.get("large")
    # 休まない検査の結果（要求のスレッドで流すため、関所は休まない）
    [served] = [source for source in env.handlers.registry.served() if source.id == "large"]
    unpaused = check_sync(env.handlers.store, served)
    assert reached
    assert [response.status_code for response in responses] == [200]
    assert len(reads) == count
    # 応答の最中も止まらずに進み、合図の後も検査が続いた
    assert held
    assert after
    held_rate = len(held) / (released_at - held_from)
    after_rate = len(after) / (after[-1] - released_at)
    assert held_rate <= 0.2 * after_rate
    assert checked is not None
    assert checked.report == unpaused


# 行の読み込みで、large の文書の行のスキーマを指すパス
LARGE_ROW_SCHEMA = "schemas/large.schema.yaml"
# 1 行あたりの時間を測る配信元の文書の行の数
CALIBRATION_ROWS = 200


def many_rows_files(rows: int) -> dict[str, str]:
    """文書の種類の行を `rows` 個持つ配信元 large のファイル一式を返す。"""
    config = "name: large\ndocuments:\n" + "".join(
        f"  - id: kind-{number}\n"
        f"    paths: [kind-{number}/*.yaml]\n"
        f"    schema: {LARGE_ROW_SCHEMA}\n"
        for number in range(rows)
    )
    return {
        "project-index.yaml": config,
        LARGE_ROW_SCHEMA: "title: large\ntype: object\n",
    }


def _validation_seconds_per_row(tmp_path: Path, write_files: Callable[..., None]) -> float:
    """休まない配信元の設定の検証の、文書の行 1 つあたりの秒数を測る。"""
    root = tmp_path / "row-calibration"
    files = many_rows_files(CALIBRATION_ROWS)
    write_files(root, files)
    value = cast("dict[str, Any]", load_yaml(files["project-index.yaml"]))
    started = time.perf_counter()
    validate_source_config(value, root=root)
    return (time.perf_counter() - started) / CALIBRATION_ROWS


def test_normal_when_other_sources_loading(
    tmp_path: Path,
    write_files: Callable[..., None],
    make_source: Callable[..., Any],
    make_loading_server: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """応答の最中は、要求が指さない配信元の行の読み込みが休みを挟んで進む（正常系）。"""
    # 準備
    per_row = _validation_seconds_per_row(tmp_path, write_files)
    # 合図までの 1 秒に 1 割の速さで進む分を引いても、合図の後に 1 秒以上残る行の数
    rows = math.ceil(2 * SIGNAL_AFTER_SEC / per_row)
    large = make_source("large", many_rows_files(rows), git=False)
    sample = make_source("sample", main_files(), branch="main")
    entered = threading.Event()
    release = threading.Event()
    checks: list[float] = []
    real_list_documents = route_module.list_documents
    real_schema_violation = sources_service_module._schema_violation

    def held_list_documents(target: Any, **kwargs: Any) -> Any:
        # sample の一覧だけを、合図まで応答の最中に保つ
        if target.source.id == "sample":
            entered.set()
            release.wait(timeout=BACKGROUND_WAIT_SEC)
        return real_list_documents(target, **kwargs)

    def recorded_schema_violation(read_text: Any, read_ref: Any, index: int, value: Any) -> Any:
        # large の文書の行ごとのスキーマの検証を実行した時刻を記録する
        if value == LARGE_ROW_SCHEMA:
            checks.append(time.perf_counter())
        return real_schema_violation(read_text, read_ref, index, value)

    monkeypatch.setattr(route_module, "list_documents", held_list_documents)
    monkeypatch.setattr(sources_service_module, "_schema_violation", recorded_schema_violation)
    # large を先に並べ、起動の読み込みを合図で止めずに始める
    loading = make_loading_server(large, sample, blocked=())
    env = loading.env
    responses: list[Any] = []
    request = threading.Thread(
        target=lambda: responses.append(env.client.get("/sources/sample/docs"))
    )
    # 実行
    request.start()
    reached = entered.wait(timeout=BACKGROUND_WAIT_SEC)
    held_from = time.perf_counter()
    time.sleep(max(0.0, (checks[0] if checks else held_from) + SIGNAL_AFTER_SEC - held_from))
    released_at = time.perf_counter()
    release.set()
    request.join(timeout=BACKGROUND_WAIT_SEC)
    loading.thread.join(timeout=BACKGROUND_WAIT_SEC)
    # 検証
    held = [at for at in checks if held_from <= at <= released_at]
    after = [at for at in checks if at > released_at]
    [served] = [source for source in env.handlers.registry.served() if source.id == "large"]
    entry = load_terminal_config(env.settings_path).sources[0]
    # 休まずに読み込んだときの配信元（関所を渡さないので休まない）
    unpaused, _ = load_source(entry, index=0)
    assert reached
    assert [response.status_code for response in responses] == [200]
    assert [row["kind"] for row in responses[0].json()["documents"]] == [
        "design",
        "design",
        "notes",
    ]
    # 応答の最中も止まらずに進み、合図の後も読み込みが続いた
    assert held
    assert after
    held_rate = len(held) / (released_at - held_from)
    after_rate = len(after) / (after[-1] - released_at)
    assert held_rate <= 0.2 * after_rate
    assert unpaused is not None
    assert served.config == unpaused.config
    assert served.schemas == unpaused.schemas


def test_normal_when_same_commit_listed_twice(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    commit_all: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同じ commit の 2 回目は、ファイルと文書の行のパターンの照合をやり直さない（正常系）。"""
    # 準備
    source = make_source("sample", main_files(), branch="main")
    env = make_server(source)
    # 裏の検査と書き出しを済ませ、数える照合を要求の分だけにする
    env.wait_background()
    calls: list[str] = []
    real_collect_files = store_module.collect_files

    def counted_collect_files(root: Path, table: Any, **kwargs: Any) -> Any:
        calls.append(table.id)
        return real_collect_files(root, table, **kwargs)

    monkeypatch.setattr(store_module, "collect_files", counted_collect_files)
    first = env.client.get("/sources/sample/docs", params={"values": "true"})
    calls.clear()
    # 実行
    second = env.client.get("/sources/sample/docs", params={"values": "true"})
    second_calls = list(calls)
    commit_all(source.folder, {"design/D-3.yaml": "id: D-3\nname: 設計 3\n"}, "docs: 追加")
    after_commit = env.client.get("/sources/sample/docs", params={"values": "true"})
    # 検証
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["documents"] == first.json()["documents"]
    assert second_calls == []
    assert after_commit.status_code == 200
    assert [row["path"] for row in after_commit.json()["documents"]] == [
        "design/D-1.yaml",
        "design/D-2.yaml",
        "design/D-3.yaml",
        "notes/files.yaml",
    ]


def test_normal_when_yaml_unreadable_by_c(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """C の読み込みで読めない YAML も、pure で読み直して同じ値で返す（正常系）。"""
    # 準備
    files = main_files()
    files["notes/files.yaml"] = (
        "files:\n  - path: guide.md\n    name: 手引き\n    tags: [scope:a, topic:b]\n"
    )
    env = make_server(make_source("sample", files, branch="main"))
    pure = cast("dict[str, Any]", YAML(typ="safe", pure=True).load(files["notes/files.yaml"]))
    # 実行
    response = env.client.get("/sources/sample/docs", params={"values": "true"})
    # 検証
    documents = response.json()["documents"]
    assert response.status_code == 200
    assert documents[2]["tags"] == ["scope:a", "topic:b"]
    assert documents[2]["value"] == pure["files"][0]

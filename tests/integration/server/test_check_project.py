from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tests.integration.server.conftest import (
    DIRECT_RULE_SCHEMA,
    NOTE_LIST_SCRIPT,
    NOTE_SCHEMA,
    direct_commit_config,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# どの文書にも当たらない `auto` の条件のタブ `none` を持つ nav
NONE_NAV = (
    "nav:\n"
    "  tabs:\n"
    "    - title: none\n"
    "      items:\n"
    "        - auto: {filter: {field: tags, op: eq, values: [none]}}\n"
)
ALIAS_SCHEMA_VERSION = "v0.3.0"
# 直下の管理用の YAML を読む行 `files` と、その配下の `content/prompts/` を読む行 `prompts`
PROMPT_ROWS = (
    "  - id: files\n"
    "    paths: [files.yaml]\n"
    "    schema: schemas/files.schema.yaml\n"
    "    records: files\n"
    "    body_file: path\n"
    "  - id: prompts\n"
    "    paths: [content/prompts/**/*.yaml]\n"
    "    schema: schemas/prompt.schema.yaml\n"
)

# 行 `rules`（`docs/`）と行 `notes`（`notes/`）を、この順に持つ配信元の設定
IDS_OVERLAP_CONFIG = (
    'version: "3"\n'
    "name: sample\n"
    "default_ref: develop\n"
    "documents:\n"
    "  - id: rules\n"
    "    paths: [docs/*.yaml]\n"
    "    schema: schemas/sample.schema.yaml\n"
    "  - id: notes\n"
    "    paths: [notes/*.yaml]\n"
    "    schema: schemas/sample.schema.yaml\n"
)


# 行 `src`（管理用の YAML）・行 `yaml`（src の YAML）・無効の行 `off` が、`src/` の同じファイルを指す
SHARED_FILE_ROWS = (
    "  - id: src\n"
    "    paths: [src/files.yaml]\n"
    "    schema: schemas/files.schema.yaml\n"
    "    records: files\n"
    "    body_file: path\n"
    "  - id: yaml\n"
    "    paths: [src/*.yaml]\n"
    "    schema: schemas/loose.schema.yaml\n"
    "  - id: off\n"
    "    paths: [src/b.py]\n"
    "    schema: schemas/loose.schema.yaml\n"
    "    enabled: false\n"
)


def _listing(folder: Path) -> dict[str, str]:
    """フォルダの下のファイルのパスと中身を集める。"""
    return {
        str(path.relative_to(folder)): path.read_text(encoding="utf-8")
        for path in sorted(folder.rglob("*"))
        if path.is_file() and ".git" not in path.parts
    }


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_sync_file_set: Callable[..., dict[str, str]],
) -> None:
    """検証に通る配信元の違反 0 件と同期の件数を返す（正常系）。"""
    # 準備
    sample = make_source("sample", sample_sync_file_set(1), git=False)
    env = make_server(sample)
    before = _listing(sample.folder)
    # 実行
    result = env.call_admin("check_project", path=str(sample.folder), format="json")
    # 検証
    assert not result.is_error
    assert "violations" not in result.data
    assert "missing_paths" not in result.data
    assert "script_errors" not in result.data
    assert result.data["version_state"] == "current"
    assert result.data["sync"]["unindexed_files"] == 1
    assert [item["path"] for item in result.data["sync"]["items"]] == ["src: src/extra0.py"]
    assert _listing(sample.folder) == before


def test_normal_when_files_excluded(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_sync_file_set: Callable[..., dict[str, str]],
) -> None:
    """除外の条件に当たるファイルを索引に無いファイルとして数えない（正常系）。"""
    # 準備
    files = sample_sync_file_set(0)
    files.update(
        {
            "src/files.yaml": "files: []\n",
            "src/a.py": "a = 1\n",
            "src/b.py": "b = 2\n",
            "src/pkg/__init__.py": "",
            "src/uv.lock": "version = 1\n",
        }
    )
    sample = make_source("sample", files, git=False)
    (sample.folder / "src" / "logo.png").write_bytes(b"\x00PNG\r\n")
    env = make_server(sample)
    # 実行
    result = env.call_admin("check_project", path=str(sample.folder), format="json")
    # 検証
    assert not result.is_error
    assert result.data["sync"]["unindexed_files"] == 3
    assert [item["path"] for item in result.data["sync"]["items"]] == [
        "src: src/a.py",
        "src: src/b.py",
        "src: src/uv.lock",
    ]


def test_normal_when_file_belongs_to_other_row(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_sync_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """管理用の YAML のフォルダの配下でも、ほかの行の文書になるファイルを数えない（正常系）。"""
    # 準備
    files = sample_sync_file_set(0)
    files.update(
        {
            "project-index.yaml": sample_config_text(PROMPT_ROWS, version="3"),
            "schemas/prompt.schema.yaml": "title: プロンプト\ntype: object\n",
            # 配信元の直下の管理用の YAML は、ほかの行の文書でない設定・スキーマ・コードを記載する
            "files.yaml": (
                "files:\n"
                "  - path: project-index.yaml\n"
                "  - path: schemas/files.schema.yaml\n"
                "  - path: schemas/prompt.schema.yaml\n"
                "  - path: schemas/sample.schema.yaml\n"
                "  - path: src/a.py\n"
            ),
            "content/prompts/p.yaml": "id: p\nname: プロンプト\n",
        }
    )
    del files["src/files.yaml"]
    sample = make_source("sample", files, git=False)
    env = make_server(sample)
    # 実行
    result = env.call_admin("check_project", path=str(sample.folder), format="json")
    # 検証
    assert not result.is_error
    assert "violations" not in result.data
    assert result.data["sync"]["unindexed_files"] == 0
    assert "items" not in result.data["sync"]


def test_normal_when_rows_share_file(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_sync_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """2 つ以上の有効な documents の行が文書にする同じファイルを、同期の件数と内訳で返却する（正常系）。"""
    # 準備
    files = sample_sync_file_set(0)
    files.update(
        {
            "project-index.yaml": sample_config_text(SHARED_FILE_ROWS, version="3"),
            "schemas/loose.schema.yaml": "title: 緩いスキーマ\ntype: object\n",
            "src/files.yaml": "files:\n  - path: a.yaml\n  - path: b.py\n",
            # 行 `src` と行 `yaml` の文書の ID も重なる
            "src/a.yaml": "id: src/a.yaml\nname: A\n",
            "src/b.py": "b = 1\n",
        }
    )
    del files["src/a.py"]
    sample = make_source("sample", files, git=False)
    env = make_server(sample)
    # 実行
    result = env.call_admin("check_project", path=str(sample.folder), format="json")
    # 検証
    assert not result.is_error
    assert "violations" not in result.data
    assert result.data["sync"]["duplicate_files"] == 1
    items = [item for item in result.data["sync"]["items"] if item["kind"] == "duplicate_files"]
    assert [item["path"] for item in items] == ["src/a.yaml: src・yaml"]
    # `src/a.yaml` の 2 つの文書の ID の重なりは、同じファイルの重なりのため数えない
    assert result.data["sync"]["duplicate_ids"] == 0


def test_normal_when_ids_overlap(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """ID が先の文書と重なり配信から除外した文書を、同期の件数と内訳で返却する（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "project-index.yaml": IDS_OVERLAP_CONFIG,
            "docs/a.yaml": "id: a\nname: A\n",
            "docs/b.yaml": "id: a\nname: B\n",
            "notes/c.yaml": "id: a\nname: C\n",
            "notes/d.yaml": "id: d\nname: D\n",
        }
    )
    del files["docs/doc-1.yaml"]
    del files["docs/doc-2.yaml"]
    sample = make_source("sample", files, git=False)
    env = make_server(sample)
    # 実行
    result = env.call_admin("check_project", path=str(sample.folder), format="json")
    # 検証
    assert not result.is_error
    assert "violations" not in result.data
    assert result.data["sync"]["duplicate_ids"] == 2
    assert result.data["sync"]["duplicate_files"] == 0
    items = [
        item["path"] for item in result.data["sync"]["items"] if item["kind"] == "duplicate_ids"
    ]
    assert items == [
        "a: rules（docs/a.yaml）・rules（docs/b.yaml）",
        "a: rules（docs/a.yaml）・notes（notes/c.yaml）",
    ]
    assert not any("notes/d.yaml" in item["path"] for item in result.data["sync"]["items"])


def test_normal_when_nested_index_and_exclude_path(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_sync_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """直下の管理用の YAML で、深い管理用の YAML の範囲と exclude のパスを数えない（正常系）。"""
    # 準備
    files = sample_sync_file_set(0)
    root_row = (
        "  - id: root\n"
        "    paths: [files.yaml]\n"
        "    schema: schemas/files.schema.yaml\n"
        "    records: files\n"
        "    body_file: path\n"
        "    exclude: ['docs/pr/**']\n"
    )
    src_row = (
        "  - id: src\n"
        "    paths: [src/files.yaml]\n"
        "    schema: schemas/files.schema.yaml\n"
        "    records: files\n"
        "    body_file: path\n"
    )
    files.update(
        {
            "project-index.yaml": sample_config_text(root_row + src_row, version="3"),
            "files.yaml": (
                "files:\n"
                "  - path: project-index.yaml\n"
                "  - path: schemas/files.schema.yaml\n"
                "  - path: schemas/sample.schema.yaml\n"
            ),
            "src/b.py": "b = 2\n",
            "docs/pr/1/README.md": "# PR 1\n",
        }
    )
    sample = make_source("sample", files, git=False)
    env = make_server(sample)
    # 実行
    result = env.call_admin("check_project", path=str(sample.folder), format="json")
    # 検証
    assert not result.is_error
    assert "violations" not in result.data
    assert result.data["sync"]["unindexed_files"] == 1
    assert [item["path"] for item in result.data["sync"]["items"]] == ["src: src/b.py"]


def test_normal_when_related_unresolved(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_sync_file_set: Callable[..., dict[str, str]],
) -> None:
    """どの文書にも当たらない関連を、同期の件数と内訳で返す（正常系）。"""
    # 準備
    files = sample_sync_file_set(0)
    files.update(
        {
            "src/files.yaml": (
                "files:\n"
                "  - path: a.py\n"
                "    related:\n"
                "      - {to: src/b.py, type: tests}\n"
                "      - {to: src/z.py, type: tests}\n"
                "      - {to: other-doc, type: tests, source: other}\n"
                "  - path: b.py\n"
            ),
            "src/a.py": "a = 1\n",
            "src/b.py": "b = 2\n",
        }
    )
    sample = make_source("sample", files, git=False)
    env = make_server(sample)
    # 実行
    result = env.call_admin("check_project", path=str(sample.folder), format="json")
    # 検証
    assert not result.is_error
    assert result.data["sync"]["unresolved_related"] == 1
    paths = [item["path"] for item in result.data["sync"]["items"]]
    assert paths == ["src: src/a.py: src/z.py"]
    assert not any("src/b.py" in path or "other-doc" in path for path in paths)


def test_normal_when_records_schema_mismatch(
    tmp_path: Path,
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
) -> None:
    """records の行のスキーマが行に合わなければ、その行の schema を違反にする（正常系）。"""
    # 準備
    env = make_server(make_source("sample"))
    before = env.handlers.registry.statuses()
    folder = tmp_path / "mismatch"
    folder.mkdir()
    (folder / "project-index.yaml").write_text(
        "name: mismatch\n"
        "documents:\n"
        "  - id: docs\n"
        "    paths: [files.yaml]\n"
        "    schema: schemas/files.schema.yaml\n"
        "    records: files\n"
        "    body_file: path\n",
        encoding="utf-8",
    )
    (folder / "schemas").mkdir()
    (folder / "schemas" / "files.schema.yaml").write_text(
        "title: file\ntype: object\nrequired: [files]\nproperties:\n  files:\n    type: array\n",
        encoding="utf-8",
    )
    (folder / "files.yaml").write_text("files:\n  - path: a.md\n", encoding="utf-8")
    (folder / "a.md").write_text("# a\n", encoding="utf-8")
    # 実行
    result = env.call_admin("check_project", path=str(folder), format="json")
    # 検証
    violations = result.data["violations"]
    assert [item["path"] for item in violations] == ["documents[0].schema"]
    assert "properties.files.items" in violations[0]["rule"]
    assert "sync" not in result.data
    assert env.handlers.registry.statuses() == before


def test_normal_when_config_has_violations(tmp_path: Path, make_server: Callable[..., Any]) -> None:
    """スキーマに違反する設定と、書く前の `config` の違反を返す（正常系）。"""
    # 準備
    env = make_server()
    folder = tmp_path / "draft"
    folder.mkdir()
    (folder / "project-index.yaml").write_text(
        "name: draft\ndocuments:\n  - id: sample\n    paths: [docs/*.yaml]\n"
        "    schema: schemas/none.schema.yaml\n",
        encoding="utf-8",
    )
    broken = "name: draft\ndocuments:\n  - id: sample\n    schema: schemas/sample.schema.yaml\n"
    # 実行
    result = env.call_admin("check_project", path=str(folder), config=broken, format="json")
    # 検証
    assert any(item["path"] == "documents[0].paths" for item in result.data["violations"])
    assert "sync" not in result.data


def test_normal_when_config_legacy(tmp_path: Path, make_server: Callable[..., Any]) -> None:
    """前の形式のキーを持つ設定の違反と、設定のバージョンが古いことを返す（正常系）。"""
    # 準備
    env = make_server()
    legacy = (
        'version: "1"\n'
        "name: legacy\n"
        "documents:\n"
        "  - id: notes\n"
        "    paths: [docs/*.md]\n"
        "    schema: schemas/sample.schema.yaml\n"
        "    type: markdown\n"
        "    defaults:\n"
        "      - paths: [docs/**]\n"
        "        tags: [doc]\n"
        "  - id: rules\n"
        "    paths: [docs/*.yaml]\n"
        "    schema: schemas/sample.schema.yaml\n"
        "    metadata:\n"
        "      name: {type: ref, field: title}\n"
    )
    # 実行
    result = env.call_admin("check_project", path=str(tmp_path), config=legacy, format="json")
    # 検証
    paths = {item["path"] for item in result.data["violations"]}
    assert {"documents[0].type", "documents[0].defaults", "documents[1].metadata.name"} <= paths
    assert result.data["version_state"] == "old"
    assert result.data["config_version"] == "1"


def test_normal_when_legacy_config_name(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """project-index.yaml が無く dev-docs.yaml があるフォルダは dev-docs.yaml を検査する（正常系）。"""
    # 準備
    files = sample_file_set()
    files["dev-docs.yaml"] = files.pop("project-index.yaml")
    legacy = make_source("legacy", files, git=False, config_names=("dev-docs.yaml",))
    env = make_server(make_source("sample"))
    # 実行
    result = env.call_admin("check_project", path=str(legacy.folder), format="json")
    (legacy.folder / "project-index.yaml").write_text(
        sample_config_text(name="renamed", extra="  - id: broken\n"), encoding="utf-8"
    )
    renamed = env.call_admin("check_project", path=str(legacy.folder), format="json")
    # 検証
    assert not result.is_error
    assert "violations" not in result.data
    assert result.data["path"] == str(legacy.folder)
    assert not renamed.is_error
    assert any(item["path"].startswith("documents[1]") for item in renamed.data["violations"])


def test_error_when_config_not_found(tmp_path: Path, make_server: Callable[..., Any]) -> None:
    """project-index.yaml の無いフォルダを指すと断る（異常系）。"""
    # 準備
    env = make_server()
    folder = tmp_path / "empty"
    folder.mkdir()
    # 実行
    result = env.call_admin("check_project", path=str(folder))
    # 検証
    assert result.is_error
    assert result.text.startswith("ConfigNotFoundError")
    assert str(folder / "project-index.yaml") in result.text


def test_error_when_config_unparsable(tmp_path: Path, make_server: Callable[..., Any]) -> None:
    """読めない config を渡すと、行と理由を返して断る（異常系）。"""
    # 準備
    env = make_server()
    # 実行
    result = env.call_admin("check_project", path=str(tmp_path), config="name: [")
    # 検証
    assert result.is_error
    assert result.text.startswith("ConfigParseError")


def test_normal_when_alias_and_nav_checked(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    alias_file_set: Callable[..., dict[str, str]],
) -> None:
    """エイリアスのキーの違反と、どの文書にも当たらない nav の条件を返す（正常系）。"""
    # 準備
    sample = make_source("sample", alias_file_set(NONE_NAV, broken=True), git=False)
    env = make_server(sample)
    # 実行
    result = env.call_admin("check_project", path=str(sample.folder), format="json")
    # 検証
    alias_violations = [item for item in result.data["violations"] if item["path"] == "aliases"]
    assert not result.is_error
    assert len(alias_violations) == 1
    assert alias_violations[0]["doc"] == "terms/broken.yaml"
    assert "文字列か文字列の並び" in alias_violations[0]["rule"]
    assert len(result.data["warnings"]) == 1
    assert "none" in result.data["warnings"][0]["rule"]
    assert result.data["alias_schema_version"] == ALIAS_SCHEMA_VERSION


def test_normal_when_schema_from_other_source(
    tmp_path: Path,
    make_schemas_source: Callable[..., Any],
    make_server: Callable[..., Any],
    ref_config_text: Callable[..., str],
) -> None:
    """documents[].schema で指したほかの配信元のリビジョンのスキーマを読み、違反 0 件を返す（正常系）。"""
    # 準備
    schemas = make_schemas_source({"schemas/note.schema.yaml": "title: [壊れた\n"})
    env = make_server(schemas)
    folder = tmp_path / "sample"
    folder.mkdir()
    (folder / "project-index.yaml").write_text(
        ref_config_text(
            "sample",
            [{"source": "schemas", "path": "schemas/note.schema.yaml", "ref": "v1"}],
        ),
        encoding="utf-8",
    )
    # 実行
    result = env.call_admin("check_project", path=str(folder), format="json")
    # 検証
    assert result.data.get("violations", []) == []


def test_normal_when_schema_ref_not_found(
    tmp_path: Path,
    make_schemas_source: Callable[..., Any],
    make_server: Callable[..., Any],
    ref_config_text: Callable[..., str],
) -> None:
    """documents[].schema の参照先の配信元・リビジョン・パスが見つからないとき、その行の schema を違反にする（正常系）。"""
    # 準備
    schemas = make_schemas_source({"notes/a.yaml": "id: a\n"})
    env = make_server(schemas)
    before = env.handlers.registry.statuses()
    folder = tmp_path / "sample"
    folder.mkdir()
    (folder / "project-index.yaml").write_text(
        ref_config_text(
            "sample",
            [
                {"source": "nothing", "path": "schemas/note.schema.yaml", "ref": "v1"},
                {"source": "schemas", "path": "schemas/note.schema.yaml", "ref": "v9"},
                {"source": "schemas", "path": "schemas/none.schema.yaml", "ref": "v1"},
            ],
        ),
        encoding="utf-8",
    )
    # 実行
    result = env.call_admin("check_project", path=str(folder), format="json")
    # 検証
    assert [(item["path"], item["rule"]) for item in result.data["violations"]] == [
        ("documents[0].schema", "配信元 nothing が端末の設定にありません"),
        ("documents[1].schema", "配信元 schemas に v9 がありません"),
        ("documents[2].schema", "v1 に schemas/none.schema.yaml がありません"),
    ]
    assert env.handlers.registry.statuses() == before


def _node_config(name: str, paths_base: str, paths: str) -> str:
    """ノードのフォルダに置く、paths_base を持つ配信元の設定の YAML を作る。"""
    return (
        f"name: {name}\n"
        f"paths_base: {paths_base}\n"
        "documents:\n"
        "  - id: note\n"
        f"    paths: {paths}\n"
        "    schema: note.schema.yaml\n"
    )


def test_normal_when_paths_base_or_paths_out_of_range(
    git_repo: Callable[..., Path],
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
) -> None:
    """paths_base が設定ファイルのフォルダより上でない・リポジトリの直下より上を指す違反と、paths が基準のフォルダの外を指す違反を返す（正常系）。"""
    # 準備
    schema = "title: note\ntype: object\n"
    in_range = "[docs/knowhow/*.yaml, content/node-docs/shared/*.yaml]"
    repo = git_repo(
        {
            "content/node-docs/brain/project-index.yaml": _node_config(
                "brain",
                "sub",
                "[docs/knowhow/*.yaml, content/node-docs/shared/*.yaml, ../outside/*.yaml]",
            ),
            "content/node-docs/brain/note.schema.yaml": schema,
            "content/node-docs/brain/sub/.keep": "",
            "content/node-docs/edge/project-index.yaml": _node_config(
                "edge", "../../../..", in_range
            ),
            "content/node-docs/edge/note.schema.yaml": schema,
            "content/node-docs/ok/project-index.yaml": _node_config("ok", "../../..", in_range),
            "content/node-docs/ok/note.schema.yaml": schema,
        },
        name="nodes",
    )
    env = make_server(make_source("sample"))
    before = env.handlers.registry.statuses()
    nodes = repo / "content" / "node-docs"
    # 実行
    brain = env.call_admin(
        "check_project", path=str(nodes / "brain" / "project-index.yaml"), format="json"
    )
    edge = env.call_admin(
        "check_project", path=str(nodes / "edge" / "project-index.yaml"), format="json"
    )
    ok = env.call_admin(
        "check_project", path=str(nodes / "ok" / "project-index.yaml"), format="json"
    )
    # 検証
    assert sorted((v["path"], v["rule"]) for v in brain.data["violations"]) == [
        ("documents[0].paths[2]", "配信元の外を指しています: ../outside/*.yaml"),
        ("paths_base", "設定ファイルのフォルダかそれより上のフォルダを指してください: sub"),
    ]
    assert [(v["path"], v["rule"]) for v in edge.data["violations"]] == [
        ("paths_base", "リポジトリの外を指しています: ../../../..")
    ]
    assert "violations" not in ok.data or ok.data["violations"] == []
    assert env.handlers.registry.statuses() == before


def test_normal_when_disk_storage(
    make_local_source: Callable[..., Any],
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
) -> None:
    """storage_type: disk と設定のファイルの絶対パスで、commit していない配信元を検査する（正常系）。"""
    # 準備（company は端末の設定に行が無い）
    company = make_local_source()
    env = make_server(make_source("sample"))
    config = str(company.config[0])
    # 実行
    result = env.call_admin("check_project", path=config, storage_type="disk", format="json")
    # 検証
    assert not result.is_error
    assert "violations" not in result.data
    assert result.data["sync"]["unindexed_files"] == 0
    assert "items" not in result.data["sync"]


def test_normal_when_local_files_excluded(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_sync_file_set: Callable[..., dict[str, str]],
    write_files: Callable[[Path, dict[str, str]], None],
) -> None:
    """コミットする運用の配信元でも *.local.* の名前のファイルを索引に無いファイルに数えない（正常系）。"""
    # 準備
    sample = make_source("sample", sample_sync_file_set(0))
    write_files(sample.folder, {"src/settings.local.json": "{}\n"})
    env = make_server(sample)
    # 実行
    result = env.call_admin("check_project", path=str(sample.folder), format="json")
    # 検証
    assert not result.is_error
    assert result.data["sync"]["unindexed_files"] == 0
    assert "items" not in result.data["sync"]


def test_normal_when_git_file_and_ignored_files(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_sync_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
    write_files: Callable[[Path, dict[str, str]], None],
) -> None:
    """ワークツリーの .git のファイルと、Git の配信元で Git が無視するファイルを数えない（正常系）。"""
    # 準備
    files = sample_sync_file_set(0)
    root_row = (
        "  - id: root\n"
        "    paths: [files.yaml]\n"
        "    schema: schemas/files.schema.yaml\n"
        "    records: files\n"
        "    body_file: path\n"
    )
    src_row = (
        "  - id: src\n"
        "    paths: [src/files.yaml]\n"
        "    schema: schemas/files.schema.yaml\n"
        "    records: files\n"
        "    body_file: path\n"
    )
    files.update(
        {
            "project-index.yaml": sample_config_text(root_row + src_row, version="3"),
            ".gitignore": ".pytest_cache/\ndist/\n",
            "files.yaml": (
                "files:\n"
                "  - path: .gitignore\n"
                "  - path: project-index.yaml\n"
                "  - path: schemas/files.schema.yaml\n"
                "  - path: schemas/sample.schema.yaml\n"
            ),
        }
    )
    sample = make_source("sample", files)
    worktree = add_worktree(sample.folder, "x")
    write_files(
        worktree,
        {".pytest_cache/x": "x\n", "dist/app.js": "app\n", "docs/new.md": "# new\n"},
    )
    env = make_server(sample)
    # 実行
    result = env.call_admin("check_project", path=str(worktree), format="json")
    # 検証
    assert not result.is_error
    assert (worktree / ".git").is_file()
    assert result.data["sync"]["unindexed_files"] == 1
    assert [item["path"] for item in result.data["sync"]["items"]] == ["root: docs/new.md"]


DIRECT_FILES = {
    "schemas/note.schema.yaml": NOTE_SCHEMA,
    "schemas/rule.schema.yaml": DIRECT_RULE_SCHEMA,
    "scripts/list.py": NOTE_LIST_SCRIPT,
    "notes/n1.yaml": "id: n1\nname: メモ 1\n",
}


@pytest.mark.parametrize(
    ("config", "expected_violations", "expected_warnings"),
    [
        pytest.param(
            direct_commit_config().replace("kinds: [note]", "kinds: note"),
            {"direct_commit.kinds": "型が違う（期待: array）"},
            {},
            id="type",
        ),
        pytest.param(
            direct_commit_config(kinds=("note", "meme")),
            {"direct_commit.kinds[1]": "meme は documents[] に無く、直コミットを断る"},
            {"direct_commit.branch": "develop を指すワークツリーが無いため、直コミットは断られる"},
            id="missing-kind",
        ),
    ],
)
def test_normal_when_direct_commit_checked(
    config: str,
    expected_violations: dict[str, str],
    expected_warnings: dict[str, str],
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
) -> None:
    """直コミットの設定を検査する（正常系）。"""
    # 準備
    sample = make_source(
        "sample", {"project-index.yaml": direct_commit_config(), **DIRECT_FILES}, branch="master"
    )
    env = make_server(sample)
    # 実行
    result = env.call_admin("check_project", path=str(sample.folder), config=config, format="json")
    # 検証
    violations = {item["path"]: item["rule"] for item in result.data["violations"]}
    warnings = {item["path"]: item["rule"] for item in result.data.get("warnings", [])}
    assert not result.is_error, result.text
    assert violations == expected_violations
    assert warnings == expected_warnings


def test_normal_when_search_exclude_invalid(
    tmp_path: Path, make_server: Callable[..., Any]
) -> None:
    """比べ方の一覧に無い比べ方と、比べられない項目を持つ search_exclude を違反として返却する（正常系）。"""
    # 準備
    env = make_server()
    folder = tmp_path / "draft"
    (folder / "schemas").mkdir(parents=True)
    (folder / "schemas" / "sample.schema.yaml").write_text(
        "type: object\nproperties:\n  id: {type: string}\n", encoding="utf-8"
    )
    config = (
        "name: draft\n"
        "documents:\n"
        "  - id: assets\n"
        "    paths: [assets/*.yaml]\n"
        "    schema: schemas/sample.schema.yaml\n"
        "    search_exclude: {field: status, op: like, values: [inactive]}\n"
        "  - id: notes\n"
        "    paths: [notes/*.yaml]\n"
        "    schema: schemas/sample.schema.yaml\n"
        "    search_exclude: {field: body, op: contains, values: [廃止]}\n"
    )
    (folder / "project-index.yaml").write_text(config, encoding="utf-8")
    # 実行
    result = env.call_admin("check_project", path=str(folder), format="json")
    # 検証
    paths = [item["path"] for item in result.data["violations"]]
    assert "documents[0].search_exclude.op" in paths
    assert "documents[1].search_exclude.field" in paths


SQLITE_VIOLATION_ROWS = (
    "  - id: memos_db\n"
    "    sqlite:\n"
    "      file: data/notes.db\n"
    "      table: memos\n"
    "      columns: [{name: id, description: ID}]\n"
    "  - id: bad_column\n"
    "    sqlite:\n"
    "      file: data/notes.db\n"
    "      table: notes\n"
    "      columns: [{name: id, description: ID}]\n"
    "    metadata: {name: heading}\n"
    "  - id: missing_db\n"
    "    sqlite:\n"
    "      file: data/missing.db\n"
    "      table: notes\n"
    "      columns: [{name: id, description: ID}]\n"
)
BOTH_ROW = (
    "  - id: both\n"
    "    paths: [docs/*.yaml]\n"
    "    sqlite:\n"
    "      file: data/notes.db\n"
    "      table: notes\n"
    "      columns: [{name: id, description: ID}]\n"
)


def test_normal_when_sqlite_row_violations(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_config_text: Callable[..., str],
) -> None:
    """SQLite の表を指す行のファイル・表・列の欠けを違反にし、上限を超えた行を警告にする（正常系）。"""
    from tests.integration.server.conftest import NOTES_DB_ROW, sqlite_files, write_notes_db

    # 準備
    source = make_source("sample", sqlite_files(SQLITE_VIOLATION_ROWS, limit=1))
    worktree = add_worktree(source.folder, "x")
    db = write_notes_db(source.folder)
    before = db.read_bytes()
    env = make_server()
    both_config = sample_config_text(NOTES_DB_ROW.format(limit="") + BOTH_ROW)
    # 実行
    result = env.call_admin("check_project", path=str(worktree), format="json")
    both = env.call_admin("check_project", path=str(worktree), config=both_config, format="json")
    # 検証
    paths = [item["path"] for item in result.data["violations"]]
    assert "documents[2].sqlite.table" in paths
    assert "documents[3].metadata.name" in paths
    assert "documents[4].sqlite.file" in paths
    assert [item["path"] for item in result.data["warnings"]] == ["documents[1].sqlite.limit"]
    assert [item["path"] for item in both.data["violations"]] == ["documents[2]"]
    assert db.read_bytes() == before

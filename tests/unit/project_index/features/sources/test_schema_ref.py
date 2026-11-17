from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.sources import schema_ref as schema_ref_module
from project_index.features.sources.schema_ref import (
    SchemaRef,
    SchemaRefError,
    read_schema_ref,
    terminal_lookup,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.settings.types import SourceEntry, TerminalConfig

NOTE_SCHEMA_V1 = (
    "title: note\ntype: object\nproperties:\n  body:\n    $ref: common.schema.yaml#/$defs/text\n"
)
NOTE_SCHEMA_V2 = (
    "title: note\n"
    "type: object\n"
    "required: [owner]\n"
    "properties:\n"
    "  owner:\n"
    "    type: string\n"
    "  body:\n"
    "    $ref: common.schema.yaml#/$defs/text\n"
)
COMMON_SCHEMA_V1 = "$defs:\n  text:\n    type: string\n"
COMMON_SCHEMA_V2 = "$defs:\n  text:\n    type: string\n    extra: true\n"


@pytest.fixture
def schemas_repo(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> Path:
    """タグ `v1` の後の commit でスキーマを書き換えた、スキーマの配信元のリポジトリを作る。"""
    root = git_repo(
        {
            "project-index.yaml": "name: schemas\ndocuments: []\n",
            "schemas/note.schema.yaml": NOTE_SCHEMA_V1,
            "schemas/common.schema.yaml": COMMON_SCHEMA_V1,
        },
        name="schemas",
    )
    run_git(root, "tag", "v1")
    commit_all(
        root,
        {
            "schemas/note.schema.yaml": NOTE_SCHEMA_V2,
            "schemas/common.schema.yaml": COMMON_SCHEMA_V2,
        },
    )
    return root


def _lookup(table: dict[str, Path]) -> Callable[[str], Path | None]:
    """ID → 設定のファイルの辞書を引く関数を返す。"""
    return table.get


def test_terminal_lookup(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """`id` の無い行は設定の `name` で引ける（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "a/project-index.yaml": "name: a\ndocuments: []\n",
            "b/project-index.yaml": "name: b\ndocuments: []\n",
        },
    )
    terminal = make_terminal_config(
        sources=[
            make_entry(str(tmp_path / "a" / "project-index.yaml"), source_id="a"),
            make_entry(str(tmp_path / "b" / "project-index.yaml")),
        ]
    )
    # 実行
    lookup = terminal_lookup(terminal)
    # 検証
    assert lookup("a") == tmp_path / "a" / "project-index.yaml"
    assert lookup("b") == tmp_path / "b" / "project-index.yaml"
    assert lookup("c") is None


def test_read_schema_ref(schemas_repo: Path, run_git: Callable[..., str]) -> None:
    """タグのスキーマを読む（正常系）。"""
    # 準備
    ref = SchemaRef(source="schemas", path="schemas/note.schema.yaml", ref="v1")
    lookup = _lookup({"schemas": schemas_repo / "project-index.yaml"})
    commit = run_git(schemas_repo, "rev-parse", "v1").strip()
    # 実行
    result = read_schema_ref(ref, lookup=lookup)
    # 検証
    assert result.schema == {
        "title": "note",
        "type": "object",
        "properties": {"body": {"type": "string"}},
    }
    assert result.commit == commit


@pytest.mark.parametrize(
    ("values", "rule"),
    [
        pytest.param(
            {"source": "nothing", "path": "schemas/note.schema.yaml", "ref": "v1"},
            "配信元 nothing が端末の設定にありません",
            id="source_missing",
        ),
        pytest.param(
            {"source": "plain", "path": "schemas/note.schema.yaml", "ref": "v1"},
            "配信元 plain は Git のリポジトリではありません",
            id="not_git",
        ),
        pytest.param(
            {"source": "schemas", "path": "schemas/note.schema.yaml", "ref": "v9"},
            "配信元 schemas に v9 がありません",
            id="ref_missing",
        ),
        pytest.param(
            {"source": "schemas", "path": "schemas/none.schema.yaml", "ref": "v1"},
            "v1 に schemas/none.schema.yaml がありません",
            id="path_missing",
        ),
        pytest.param(
            {"source": "schemas", "path": "schemas/broken.schema.yaml", "ref": "v1"},
            "v1 に schemas/missing.schema.yaml がありません",
            id="ref_target_missing",
        ),
    ],
)
def test_read_schema_ref_when_not_found(
    values: dict[str, Any],
    rule: str,
    tmp_path: Path,
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    write_files: Callable[[Path, dict[str, str]], None],
) -> None:
    """参照先が見つからない（異常系）。"""
    # 準備
    schemas = git_repo(
        {
            "project-index.yaml": "name: schemas\ndocuments: []\n",
            "schemas/note.schema.yaml": NOTE_SCHEMA_V1,
            "schemas/common.schema.yaml": COMMON_SCHEMA_V1,
            "schemas/broken.schema.yaml": "properties:\n  a:\n    $ref: missing.schema.yaml#/$defs/x\n",
        },
        name="schemas",
    )
    run_git(schemas, "tag", "v1")
    write_files(tmp_path / "plain", {"project-index.yaml": "name: plain\ndocuments: []\n"})
    lookup = _lookup(
        {
            "schemas": schemas / "project-index.yaml",
            "plain": tmp_path / "plain" / "project-index.yaml",
        }
    )
    # 実行・検証
    with pytest.raises(SchemaRefError, match=rule):
        read_schema_ref(SchemaRef(**values), lookup=lookup)


def test_read_schema_ref_when_cached(
    schemas_repo: Path,
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同じ commit の 2 回目は読み直さない（正常系）。"""
    # 準備
    calls: list[str] = []
    real = schema_ref_module.read_file_at

    def recording(repo: Path, commit: str, path: str) -> Any:
        calls.append(path)
        return real(repo, commit, path)

    monkeypatch.setattr(schema_ref_module, "read_file_at", recording)
    lookup = _lookup({"schemas": schemas_repo / "project-index.yaml"})
    tag_ref = SchemaRef(source="schemas", path="schemas/note.schema.yaml", ref="v1")
    branch_ref = SchemaRef(source="schemas", path="schemas/note.schema.yaml", ref="develop")
    first_tag = read_schema_ref(tag_ref, lookup=lookup)
    calls.clear()
    # 実行
    second_tag = read_schema_ref(tag_ref, lookup=lookup)
    tag_calls = list(calls)
    read_schema_ref(branch_ref, lookup=lookup)
    moved = commit_all(schemas_repo, {"schemas/note.schema.yaml": "title: moved\ntype: object\n"})
    after_move = read_schema_ref(branch_ref, lookup=lookup)
    # 検証
    assert tag_calls == []
    assert second_tag == first_tag
    assert after_move.commit == moved
    assert after_move.schema == {"title": "moved", "type": "object"}

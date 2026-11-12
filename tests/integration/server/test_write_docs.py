from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from project_index.shared.hashing import content_hash
from project_index.shared.yaml_io import load_yaml as load_yaml_value

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest


def load_yaml(text: str) -> Any:
    """形の分かっている YAML の文字列を読む。"""
    return load_yaml_value(text)


BROKEN_CONFIG = "name: broken\ndocuments:\n  - id: sample\n    schema: schemas/sample.schema.yaml\n"
IDS_AND_GENERATOR = (
    "ids:\n"
    '  format: "{kind}-{slug}"\n'
    "generators:\n"
    "  - id: list\n"
    "    run: [python3, scripts/list.py]\n"
)
LIST_SCRIPT = (
    "import pathlib\n"
    "names = sorted(path.stem for path in pathlib.Path('docs').glob('*.yaml'))\n"
    "out = pathlib.Path('generated')\n"
    "out.mkdir(exist_ok=True)\n"
    "(out / 'list.txt').write_text('\\n'.join(names) + '\\n')\n"
)
AFTER_WRITE_ROW = (
    "  - id: sample\n"
    "    paths: [docs/*.yaml]\n"
    "    schema: schemas/sample.schema.yaml\n"
    "    after_write: [list]\n"
)

RULES_ROW = (
    "  - id: rules\n"
    "    paths: [rules/*.yaml]\n"
    "    schema: schemas/rule.schema.yaml\n"
    "    metadata:\n"
    '      tags: "tags[].name"\n'
    '      main_tags: "tags[main].name"\n'
)
RULE_SCHEMA = (
    "type: object\n"
    "properties:\n"
    "  id: {type: string}\n"
    "  name: {type: string}\n"
    "  tags:\n"
    "    type: array\n"
    "    items:\n"
    "      type: object\n"
    "      properties:\n"
    "        name: {type: string}\n"
    "        main: {type: boolean}\n"
)
RULE_DOC = "id: r1\nname: 規約 1\ntags:\n  - {name: a, main: true}\n  - {name: b}\n"
TERM_ROW = "  - id: term\n    paths: [terms/*.yaml]\n    schema: schemas/term.schema.yaml\n"
TERM_SCHEMA = "type: object\nrequired: [id, name]\nproperties:\n  id: {type: string}\n  name: {type: string}\n"


def _version(path: Path) -> str:
    """文書のファイルの今のバージョン（内容のハッシュ）を返す。"""
    return content_hash(path.read_text(encoding="utf-8"))


def _update(doc_id: str, version: str, **operation: Any) -> dict[str, Any]:
    """`update` の操作を作る。"""
    return {"op": "update", "id": doc_id, "expected_version": version, **operation}


# 必須の `name` が説明・例を持ち、`count` が型だけを持つスキーマ
HINT_SCHEMA = (
    "type: object\n"
    "title: サンプル\n"
    "required: [id, name]\n"
    "properties:\n"
    "  id:\n"
    "    type: string\n"
    "  name:\n"
    "    type: string\n"
    "    title: 名前\n"
    "    description: 文書の名前\n"
    "    examples: [設定のリファレンス]\n"
    "  description:\n"
    "    type: string\n"
    "  tags:\n"
    "    type: array\n"
    "  count:\n"
    "    type: integer\n"
)


def _setup(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    files: dict[str, str] | None = None,
) -> tuple[Any, Any, Path]:
    """ワークツリー x を持つ sample を起動し、配信元・環境・ワークツリーを返す。"""
    source = make_source("sample", files)
    worktree = add_worktree(source.folder, "x")
    return source, make_server(source), worktree


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    run_git: Callable[..., str],
) -> None:
    """ワークツリーの文書を set で部分更新する（正常系）。"""
    # 準備
    source, env, worktree = _setup(make_source, make_server, add_worktree)
    target = worktree / "docs" / "doc-1.yaml"
    before = _version(target)
    clone_text = (source.folder / "docs" / "doc-1.yaml").read_text(encoding="utf-8")
    commits = run_git(worktree, "rev-list", "--count", "HEAD")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[_update("doc-1", before, set={"name": "新しい名前"})],
    )
    # 検証
    item = result.data["results"][0]
    written = load_yaml(target.read_text(encoding="utf-8"))
    assert not result.is_error
    assert result.data["applied"] is True
    assert item["status"] == "updated"
    assert item["version"] != before
    assert "新しい名前" in item["diff"]
    assert written["name"] == "新しい名前"
    assert written["description"] == "1 件目"
    assert (source.folder / "docs" / "doc-1.yaml").read_text(encoding="utf-8") == clone_text
    assert run_git(worktree, "rev-list", "--count", "HEAD") == commits


def test_normal_when_create(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """create で ids.format の ID の文書を作り、generators を流す（正常系）。"""
    # 準備
    config = sample_config_text(IDS_AND_GENERATOR).replace(
        "  - id: sample\n    paths: [docs/*.yaml]\n    schema: schemas/sample.schema.yaml\n",
        AFTER_WRITE_ROW,
    )
    files = sample_file_set(**{"project-index.yaml": config, "scripts/list.py": LIST_SCRIPT})
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[
            {
                "op": "create",
                "kind": "sample",
                "data": {"name": "文書 3", "description": "3 件目"},
            }
        ],
    )
    # 検証
    item = result.data["results"][0]
    created = worktree / "docs" / f"{item['id']}.yaml"
    assert not result.is_error
    assert item["status"] == "created"
    assert item["id"] == "sample-3"
    assert item["version"]
    assert created.is_file()
    assert item["id"] in (worktree / "generated" / "list.txt").read_text(encoding="utf-8")


def test_normal_when_kind_added_in_worktree(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_config_text: Callable[..., str],
) -> None:
    """ワークツリーの設定に追加した種類で作る（正常系）。"""
    # 準備
    source, env, worktree = _setup(make_source, make_server, add_worktree)
    # ワークツリーの設定にだけ種類 term を追加し、commit しない
    (worktree / "project-index.yaml").write_text(
        sample_config_text(TERM_ROW), encoding="utf-8"
    )
    (worktree / "schemas" / "term.schema.yaml").write_text(TERM_SCHEMA, encoding="utf-8")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[{"op": "create", "kind": "term", "id": "t1", "data": {"name": "用語 1"}}],
    )
    # 検証
    item = result.data["results"][0]
    assert not result.is_error
    assert item["status"] == "created"
    assert item["id"] == "t1"
    assert item["version"]
    assert (worktree / "terms" / "t1.yaml").is_file()
    assert not (source.folder / "terms").exists()


def test_normal_when_operations_combined(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """unset・add_to・remove_from・text_edits と replace を当てる（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "docs/doc-1.yaml": sample_doc_text(
                "doc-1", "文書 1", description="元の概要文", tags=["a", "b"], weight=3
            )
        }
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    first = worktree / "docs" / "doc-1.yaml"
    second = worktree / "docs" / "doc-2.yaml"
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[
            _update(
                "doc-1",
                _version(first),
                unset=["weight"],
                add_to={"tags": ["c"]},
                remove_from={"tags": ["a"]},
                text_edits=[{"field": "description", "old": "元の", "new": "新しい"}],
            ),
            {
                "op": "replace",
                "id": "doc-2",
                "expected_version": _version(second),
                "data": {"id": "doc-2", "name": "置き換え後"},
            },
        ],
    )
    # 検証
    doc_1 = load_yaml(first.read_text(encoding="utf-8"))
    doc_2 = load_yaml(second.read_text(encoding="utf-8"))
    assert [item["status"] for item in result.data["results"]] == ["updated", "replaced"]
    assert "weight" not in doc_1
    assert doc_1["tags"] == ["b", "c"]
    assert doc_1["description"] == "新しい概要文"
    assert doc_2 == {"id": "doc-2", "name": "置き換え後"}


def test_normal_when_dry_run(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
) -> None:
    """dry_run: true で検証と差分だけを返す（正常系）。"""
    # 準備
    source, env, worktree = _setup(make_source, make_server, add_worktree)
    target = worktree / "docs" / "doc-1.yaml"
    before = target.read_text(encoding="utf-8")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[_update("doc-1", _version(target), set={"name": "新しい名前"})],
        dry_run=True,
    )
    # 検証
    assert result.data["applied"] is False
    assert "新しい名前" in result.data["results"][0]["diff"]
    assert target.read_text(encoding="utf-8") == before


def test_normal_when_not_atomic(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
) -> None:
    """atomic: false で通る操作だけを書き、失敗を添字つきで返す（正常系）。"""
    # 準備
    source, env, worktree = _setup(make_source, make_server, add_worktree)
    first = worktree / "docs" / "doc-1.yaml"
    second = worktree / "docs" / "doc-2.yaml"
    second_before = second.read_text(encoding="utf-8")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[
            _update("doc-1", _version(first), set={"name": "新しい名前"}),
            _update("doc-2", _version(second), unset=["name"]),
        ],
        atomic=False,
    )
    # 検証
    results = result.data["results"]
    assert not result.is_error
    assert result.data["applied"] is True
    assert [item["status"] for item in results] == ["updated", "failed"]
    assert results[1]["errors"][0]["path"]
    assert results[1]["errors"][0]["rule"]
    assert results[1]["errors"][0]["fix"]
    assert load_yaml(first.read_text(encoding="utf-8"))["name"] == "新しい名前"
    assert second.read_text(encoding="utf-8") == second_before


def test_normal_when_non_git_source(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """Git 管理外の配信元に書き、created・updated を付ける（正常系）。"""
    # 準備
    sample = make_source("sample")
    memo_config = sample_config_text('ids:\n  format: "{kind}-{slug}"\n', name="memo")
    memo = make_source(
        "memo",
        sample_file_set(**{"project-index.yaml": memo_config}),
        git=False,
        scope_read=[sample.folder],
        scope_write=[sample.folder],
    )
    env = make_server(sample, memo)
    # 実行
    created = env.call(
        "write_docs",
        cwd=str(sample.folder),
        source="memo",
        operations=[{"op": "create", "kind": "sample", "data": {"name": "メモ 1"}}],
    )
    target = memo.folder / "docs" / f"{created.data['results'][0]['id']}.yaml"
    first = load_yaml(target.read_text(encoding="utf-8"))
    updated = env.call(
        "write_docs",
        cwd=str(sample.folder),
        source="memo",
        operations=[
            _update(
                created.data["results"][0]["id"],
                created.data["results"][0]["version"],
                set={"description": "追記"},
            )
        ],
    )
    second = load_yaml(target.read_text(encoding="utf-8"))
    # 検証
    assert created.data["results"][0]["status"] == "created"
    assert first["created"]
    assert first["updated"]
    assert updated.data["results"][0]["status"] == "updated"
    assert second["created"] == first["created"]
    assert str(second["updated"]) > str(first["updated"])


def test_error_when_validation_failed(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """1 件でも検査に通らなければ何も書かない（異常系）。"""
    # 準備
    files = sample_file_set(**{"schemas/sample.schema.yaml": HINT_SCHEMA})
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    first = worktree / "docs" / "doc-1.yaml"
    second = worktree / "docs" / "doc-2.yaml"
    first_before = first.read_text(encoding="utf-8")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[
            _update("doc-1", _version(first), set={"name": "新しい名前"}),
            _update("doc-2", _version(second), unset=["name"], set={"count": "3"}),
        ],
    )
    # 検証
    assert result.is_error
    assert "ValidationFailedError" in result.text
    assert "operations[1]" in result.text
    assert "name" in result.text
    assert "fix" in result.text
    assert "count" in result.text
    # `unset` した `name` の違反だけが、スキーマの title・description・examples を持つ
    assert result.text.count("schema:") == 1
    assert "title: 名前" in result.text
    assert "description: 文書の名前" in result.text
    assert "- 設定のリファレンス" in result.text
    assert "x-rules" not in result.text
    assert first.read_text(encoding="utf-8") == first_before


def test_error_when_source_not_writable(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """scope.write に当たらない作業場所からの書き込みを断る（異常系）。"""
    # 準備
    sample = make_source("sample")
    notes = make_source("notes", git=False, scope_read=[sample.folder])
    env = make_server(sample, notes)
    target = notes.folder / "docs" / "doc-1.yaml"
    before = target.read_text(encoding="utf-8")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(sample.folder),
        source="notes",
        operations=[_update("doc-1", _version(target), set={"name": "新しい名前"})],
    )
    # 検証
    assert result.is_error
    assert "SourceNotWritableError" in result.text
    assert "notes" in result.text
    assert "sample" in result.text
    assert target.read_text(encoding="utf-8") == before


def test_error_when_target_is_clone(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
) -> None:
    """Git の配信元のクローン本体には書かない（異常系）。"""
    # 準備
    source, env, _ = _setup(make_source, make_server, add_worktree)
    target = source.folder / "docs" / "doc-1.yaml"
    before = target.read_text(encoding="utf-8")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        operations=[_update("doc-1", _version(target), set={"name": "新しい名前"})],
    )
    # 検証
    assert result.is_error
    assert "TargetIsCloneError" in result.text
    assert "worktree" in result.text
    assert target.read_text(encoding="utf-8") == before


def test_error_when_version_mismatch(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_doc_text: Callable[..., str],
) -> None:
    """読んだときのバージョンでは、直接編集した内容を上書きしない（異常系）。"""
    # 準備
    source, env, worktree = _setup(make_source, make_server, add_worktree)
    target = worktree / "docs" / "doc-1.yaml"
    read_version = _version(target)
    arguments = {"cwd": str(source.folder), "worktree": str(worktree), "session_id": "s1"}
    env.call(
        "search_docs",
        filter={"field": "id", "op": "eq", "values": ["doc-1"]},
        view="full",
        **arguments,
    )
    edited = sample_doc_text("doc-1", "文書 1", description="直接編集した概要文", tags=["a"])
    target.write_text(edited, encoding="utf-8")
    # 実行
    mismatch = env.call(
        "write_docs",
        operations=[_update("doc-1", read_version, set={"name": "新しい名前"})],
        **arguments,
    )
    retried = env.call(
        "write_docs",
        operations=[_update("doc-1", _version(target), set={"name": "新しい名前"})],
        **arguments,
    )
    # 検証
    written = load_yaml(target.read_text(encoding="utf-8"))
    assert mismatch.is_error
    assert "VersionMismatchError" in mismatch.text
    assert _version_of(edited) in mismatch.text
    assert "直接編集した概要文" in mismatch.text
    assert retried.data["results"][0]["status"] == "updated"
    assert written["name"] == "新しい名前"
    assert written["description"] == "直接編集した概要文"


def _version_of(text: str) -> str:
    """文書の内容のバージョンを返す。"""
    return content_hash(text)


def test_error_when_unknown_kind(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
) -> None:
    """配信元に無い kind の create を断る（異常系）。"""
    # 準備
    source, env, worktree = _setup(make_source, make_server, add_worktree)
    files = sorted(path.name for path in (worktree / "docs").iterdir())
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[{"op": "create", "kind": "no-such-kind", "data": {"name": "x"}}],
    )
    # 検証
    assert result.is_error
    assert "UnknownKindError" in result.text
    assert "no-such-kind" in result.text
    assert "sample" in result.text
    assert sorted(path.name for path in (worktree / "docs").iterdir()) == files


def test_error_when_document_not_found(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
) -> None:
    """無い id の update を断る（異常系）。"""
    # 準備
    source, env, worktree = _setup(make_source, make_server, add_worktree)
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[_update("doc-l", "000000", set={"name": "x"})],
    )
    # 検証
    assert result.is_error
    assert "DocumentNotFoundError" in result.text
    assert "doc-l" in result.text
    assert "doc-1" in result.text


def test_error_when_invalid_argument(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """件数の上限・必須のキー・text_edits の一致を確かめる（異常系）。"""
    # 準備
    files = sample_file_set(
        **{"docs/doc-1.yaml": sample_doc_text("doc-1", "文書 1", description="重複 重複")}
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    target = worktree / "docs" / "doc-1.yaml"
    before = target.read_text(encoding="utf-8")
    arguments = {"cwd": str(source.folder), "worktree": str(worktree)}
    version = _version(target)
    # 実行
    too_many = env.call(
        "write_docs",
        operations=[_update("doc-1", version, set={"name": "x"})] * 51,
        **arguments,
    )
    no_version = env.call(
        "write_docs",
        operations=[{"op": "update", "id": "doc-1", "set": {"name": "x"}}],
        **arguments,
    )
    ambiguous = env.call(
        "write_docs",
        operations=[
            _update(
                "doc-1",
                version,
                text_edits=[{"field": "description", "old": "重複", "new": "一意"}],
            )
        ],
        **arguments,
    )
    # 検証
    assert too_many.is_error
    assert "50" in too_many.text
    assert no_version.is_error
    assert "operations[0].expected_version" in no_version.text
    assert ambiguous.is_error
    assert "2" in ambiguous.text
    assert "replace_all" in ambiguous.text
    assert target.read_text(encoding="utf-8") == before


def test_error_when_source_not_served(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """起動時の検証で外した配信元への書き込みを断る（異常系）。"""
    # 準備
    sample = make_source("sample")
    broken = make_source(
        "broken",
        {"project-index.yaml": BROKEN_CONFIG},
        scope_read=[sample.folder],
        scope_write=[sample.folder],
    )
    env = make_server(sample, broken)
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(sample.folder),
        source="broken",
        operations=[_update("doc-1", "000000", set={"name": "x"})],
    )
    # 検証
    assert result.is_error
    assert "SourceNotServedError" in result.text
    assert "broken" in result.text
    assert "documents[0].paths" in result.text


def test_error_when_worktree_not_matched(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    tmp_path: Path,
) -> None:
    """worktrees に当たらない worktree を断る（異常系）。"""
    # 準備
    source, env, _ = _setup(make_source, make_server, add_worktree)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(elsewhere),
        operations=[_update("doc-1", "000000", set={"name": "x"})],
    )
    # 検証
    assert result.is_error
    assert "WorktreeNotMatchedError" in result.text
    assert str(elsewhere) in result.text
    assert ".claude/worktrees" in result.text
    assert list(elsewhere.iterdir()) == []


def test_error_when_placement_excluded(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """create で決めた置き場所のファイル名が exclude に当たるとき、何も書かずに断る（異常系）。"""
    # 準備
    rule_row = (
        "  - id: rule\n"
        "    paths: [docs/rule/*.yaml]\n"
        "    schema: schemas/sample.schema.yaml\n"
        "    exclude: [index.yaml]\n"
    )
    files = sample_file_set(**{"project-index.yaml": sample_config_text(rule_row)})
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[{"op": "create", "kind": "rule", "id": "index", "data": {"name": "目次"}}],
    )
    # 検証
    assert result.is_error
    assert "InvalidArgumentError" in result.text
    assert "operations[0].kind" in result.text
    assert "docs/rule/index.yaml" in result.text
    assert "exclude" in result.text
    assert not (worktree / "docs" / "rule" / "index.yaml").exists()


def test_normal_when_metadata_mapped(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """共通のキー名で書く（正常系）。"""
    # 準備
    decisions_row = (
        "  - id: decisions\n"
        "    paths: [decisions/*.yaml]\n"
        "    schema: schemas/decision.schema.yaml\n"
        "    metadata: {name: title}\n"
    )
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(decisions_row),
            "schemas/decision.schema.yaml": "type: object\nrequired: [id, title]\n",
            "decisions/d1.yaml": "id: d1\ntitle: 決定 1\n",
        }
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    target = worktree / "decisions" / "d1.yaml"

    def write(*operations: dict[str, Any]) -> Any:
        return env.call(
            "write_docs",
            cwd=str(source.folder),
            worktree=str(worktree),
            operations=list(operations),
        )

    # 実行
    renamed = write(_update("d1", _version(target), set={"name": "新しい名前"}))
    renamed_text = target.read_text(encoding="utf-8")
    created = write({"op": "create", "kind": "decisions", "id": "d2", "data": {"name": "決定 2"}})
    created_text = (worktree / "decisions" / "d2.yaml").read_text(encoding="utf-8")
    by_column = write(_update("d1", _version(target), set={"title": "別の名前"}))
    by_column_text = target.read_text(encoding="utf-8")
    both = write(_update("d1", _version(target), set={"name": "a", "title": "b"}))
    # 検証
    assert renamed.data["results"][0]["status"] == "updated"
    assert "title: 新しい名前" in renamed.data["results"][0]["diff"]
    assert "name:" not in renamed_text
    assert created.data["results"][0]["status"] == "created"
    assert "title: 決定 2" in created_text
    assert "name:" not in created_text
    assert by_column.data["results"][0]["status"] == "updated"
    assert "title: 別の名前" in by_column_text
    assert both.is_error
    assert "InvalidArgumentError" in both.text
    assert "operations[0].set.name" in both.text
    assert target.read_text(encoding="utf-8") == by_column_text


def test_normal_when_tool_description(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """ツールの説明に、範囲のファイルの増減・改名で管理用の YAML の行を修正することを含める（正常系）。"""
    # 準備
    env = make_server(make_source("sample"))
    # 実行
    response = env.client.post(
        "/mcp/",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    # 検証
    tools = {tool["name"]: tool for tool in response.json()["result"]["tools"]}
    assert (
        "範囲のファイルを作成・削除・改名したら、管理用の YAML の行を修正する"
        in tools["write_docs"]["description"]
    )


def _write_tags(env: Any, source: Any, worktree: Path, step: dict[str, Any]) -> tuple[Any, Any]:
    """r1 に update を 1 回当て、結果と書いた後の tags を返す。"""
    target = worktree / "rules" / "r1.yaml"
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[_update("r1", _version(target), **step)],
    )
    return result, load_yaml(target.read_text(encoding="utf-8"))["tags"]


def test_normal_when_tags_are_objects(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """tags[].name の対応を持つ種類で、tags・main_tags への操作をオブジェクトの配列へ書き戻す（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(RULES_ROW),
            "schemas/rule.schema.yaml": RULE_SCHEMA,
            "rules/r1.yaml": RULE_DOC,
        }
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    # 実行
    first, tags_1 = _write_tags(env, source, worktree, {"add_to": {"tags": ["c"]}})
    second, tags_2 = _write_tags(env, source, worktree, {"remove_from": {"tags": ["b"]}})
    third, tags_3 = _write_tags(env, source, worktree, {"set": {"tags": ["a", "c", "d"]}})
    fourth, tags_4 = _write_tags(env, source, worktree, {"set": {"main_tags": ["c"]}})
    fifth, tags_5 = _write_tags(env, source, worktree, {"set": {"main_tags": ["z"]}})
    sixth, tags_6 = _write_tags(env, source, worktree, {"add_to": {"main_tags": ["d"]}})
    seventh, tags_7 = _write_tags(env, source, worktree, {"remove_from": {"main_tags": ["c"]}})
    eighth, tags_8 = _write_tags(env, source, worktree, {"unset": ["main_tags"]})
    ninth = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[
            {
                "op": "create",
                "kind": "rules",
                "data": {"id": "r2", "tags": [{"name": "a", "main": True}]},
            }
        ],
    )
    tenth, tags_10 = _write_tags(env, source, worktree, {"set": {"tags": "a"}})
    eleventh, tags_11 = _write_tags(env, source, worktree, {"add_to": {"tags": [{"name": "c"}]}})
    # 検証
    assert not first.is_error
    assert tags_1 == [{"name": "a", "main": True}, {"name": "b"}, {"name": "c"}]
    assert not second.is_error
    assert tags_2 == [{"name": "a", "main": True}, {"name": "c"}]
    assert not third.is_error
    assert tags_3 == [{"name": "a", "main": True}, {"name": "c"}, {"name": "d"}]
    assert not fourth.is_error
    assert tags_4 == [{"name": "a"}, {"name": "c", "main": True}, {"name": "d"}]
    assert fifth.is_error
    assert "InvalidArgumentError" in fifth.text
    assert "z" in fifth.text
    assert tags_5 == [{"name": "a"}, {"name": "c", "main": True}, {"name": "d"}]
    assert not sixth.is_error
    assert tags_6 == [{"name": "a"}, {"name": "c", "main": True}, {"name": "d", "main": True}]
    assert not seventh.is_error
    assert tags_7 == [{"name": "a"}, {"name": "c"}, {"name": "d", "main": True}]
    assert not eighth.is_error
    assert tags_8 == [{"name": "a"}, {"name": "c"}, {"name": "d"}]
    assert ninth.is_error
    assert "InvalidArgumentError" in ninth.text
    assert "operations[0].data.tags" in ninth.text
    assert "名前（文字列）の配列" in ninth.text
    assert not (worktree / "rules" / "r2.yaml").exists()
    assert tenth.is_error
    assert "InvalidArgumentError" in tenth.text
    assert "operations[0].set.tags" in tenth.text
    assert tags_10 == tags_8
    assert eleventh.is_error
    assert "InvalidArgumentError" in eleventh.text
    assert "operations[0].add_to.tags" in eleventh.text
    assert tags_11 == tags_8


# 単一引用符・`: ` を含む二重引用符・引用符なしの値を持つ文書 1
QUOTED_DOC = "id: doc-1\nname: \"A: b\"\ndescription: '2020-12'\nweight: 1\n"


def test_normal_when_quotes_preserved(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """書き換えた文書の、変更していない項目の引用符の種類を元のまま書き出す（正常系）。"""
    # 準備
    files = sample_file_set(**{"docs/doc-1.yaml": QUOTED_DOC})
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    target = worktree / "docs" / "doc-1.yaml"
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[_update("doc-1", _version(target), set={"weight": 2})],
    )
    # 検証
    assert not result.is_error
    assert target.read_text(encoding="utf-8") == (
        "id: doc-1\nname: \"A: b\"\ndescription: '2020-12'\nweight: 2\n"
    )
    assert result.data["results"][0]["diff"] == "- weight: 1\n+ weight: 2"


MARKDOWN_SCHEMA = (
    "type: object\n"
    "properties:\n"
    "  id: {type: string}\n"
    "  name: {type: string}\n"
    "  description: {type: string}\n"
    "  tags: {type: array, items: {type: string}}\n"
    "  body: {type: string, contentMediaType: text/markdown}\n"
)
# 図の部品を含む値には書き方の警告、embed のマーカーだけの値には知らない印を返す偽の mdmark
FAKE_MDMARK = (
    "import pathlib, sys\n"
    "text = sys.stdin.read()\n"
    "with pathlib.Path(sys.argv[0]).with_name('calls.txt').open('a', encoding='utf-8') as f:\n"
    "    f.write('call\\n')\n"
    "if '<!-- flow -->' in text:\n"
    "    print('-:3: diagram_invalid: 図の定義を読めません')\n"
    "    print('ずれ 1 件')\n"
    "    sys.exit(1)\n"
    "if '<!-- embed: x -->' in text:\n"
    "    print('-:1: unknown_mark: 知らない印 embed です')\n"
    "    print('ずれ 1 件')\n"
    "    sys.exit(1)\n"
    "print('ずれ 0 件')\n"
)
NO_SUMMARY_MDMARK = (
    "import sys\nsys.stdin.read()\nprint('unknown option --text', file=sys.stderr)\nsys.exit(1)\n"
)
FLOW_BODY = '<!-- flow -->\n\n```json\n{"nodes": [\n```\n\n<!-- /flow -->\n'


def _put_mdmark(folder: Path, code: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`code` を本体にした `mdmark` をフォルダに置き、PATH の先頭にそのフォルダを入れる。"""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "mdmark"
    script.write_text(f"#!{sys.executable}\n{code}", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    return folder


def _hide_mdmark(monkeypatch: pytest.MonkeyPatch) -> None:
    """今の PATH から mdmark を持つフォルダを除く（git などのほかのコマンドは引ける状態を保つ）。"""
    folders = os.environ["PATH"].split(os.pathsep)
    kept = [folder for folder in folders if not (Path(folder) / "mdmark").exists()]
    monkeypatch.setenv("PATH", os.pathsep.join(kept))


def _markdown_setup(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> tuple[Any, Any, Path]:
    """`body` を Markdown のキーに持つ sample を起動する。"""
    files = sample_file_set(**{"schemas/sample.schema.yaml": MARKDOWN_SCHEMA})
    return _setup(make_source, make_server, add_worktree, files)


def test_normal_when_mdmark_unavailable(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mdmark の CLI が無いか点検を終えられないときは、点検せずに書き込み、理由を返す（正常系）。"""
    # 準備
    source, env, worktree = _markdown_setup(make_source, make_server, add_worktree, sample_file_set)
    target = worktree / "docs" / "doc-1.yaml"
    _hide_mdmark(monkeypatch)
    # PATH に無いときに探すサーバーの Python の環境の bin にも mdmark が無いこと
    assert not (Path(sys.executable).parent / "mdmark").exists()
    # 実行（1 回目: PATH に mdmark が無い）
    first = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[_update("doc-1", _version(target), set={"body": FLOW_BODY})],
    )
    # 実行（2 回目: 結果を出さずに終わる mdmark）
    _put_mdmark(tmp_path / "bin-no-summary", NO_SUMMARY_MDMARK, monkeypatch)
    second = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[_update("doc-1", _version(target), set={"body": FLOW_BODY + "\n2\n"})],
    )
    # 検証
    first_item = first.data["results"][0]
    second_item = second.data["results"][0]
    assert not first.is_error
    assert first.data["applied"] is True
    assert first_item["status"] == "updated"
    assert first_item["unchecked"][0]["path"] == "body"
    assert "mdmark の CLI が PATH に見つかりません" in first_item["unchecked"][0]["reason"]
    assert not second.is_error
    assert second.data["applied"] is True
    assert second_item["status"] == "updated"
    assert "結果を出さずに終了コード 1" in second_item["unchecked"][0]["reason"]
    assert "unknown option --text" in second_item["unchecked"][0]["reason"]
    assert load_yaml(target.read_text(encoding="utf-8"))["body"] == FLOW_BODY + "\n2\n"


def test_error_when_mdmark_warning(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """変えた Markdown のキーの値に mdmark の描画時の書き方の警告があれば何も書かない（異常系）。"""
    # 準備
    bin_dir = _put_mdmark(tmp_path / "bin", FAKE_MDMARK, monkeypatch)
    source, env, worktree = _markdown_setup(make_source, make_server, add_worktree, sample_file_set)
    first = worktree / "docs" / "doc-1.yaml"
    second = worktree / "docs" / "doc-2.yaml"
    first_before = first.read_text(encoding="utf-8")
    second_before = second.read_text(encoding="utf-8")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[
            _update("doc-2", _version(second), set={"name": "通る"}),
            _update("doc-1", _version(first), set={"body": FLOW_BODY}),
        ],
    )
    calls_after_error = (bin_dir / "calls.txt").read_text(encoding="utf-8")
    first_after_error = first.read_text(encoding="utf-8")
    second_after_error = second.read_text(encoding="utf-8")
    embed = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[_update("doc-1", _version(first), set={"body": "<!-- embed: x -->\n"})],
    )
    # 検証
    assert result.is_error
    assert "ValidationFailedError" in result.text
    assert "operations[1].body" in result.text
    assert "mdmark の diagram_invalid（3 行目）" in result.text
    assert "図の定義を読めません" in result.text
    assert first_after_error == first_before
    assert second_after_error == second_before
    assert calls_after_error == "call\n"
    assert not embed.is_error
    assert embed.data["results"][0]["status"] == "updated"
    assert load_yaml(first.read_text(encoding="utf-8"))["body"] == "<!-- embed: x -->\n"

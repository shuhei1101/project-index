from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from project_index.shared.hashing import content_hash, value_hash
from project_index.shared.runtime import DOCS_WORKERS
from project_index.shared.yaml_io import load_yaml as load_yaml_value
from tests.integration.server.conftest import (
    DIRECT_RULE_SCHEMA,
    F1_BODY,
    FAILING_SCRIPT,
    FILES_INDEX,
    METADATA_ONLY_FILES,
    NOTE_LIST_SCRIPT,
    NOTE_SCHEMA,
    direct_commit_config,
    metadata_only_config,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.integration.server.conftest import DirectCommitSource


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


# `$defs.entry` が別のファイルの `summary` を相対パスで指し、`children` で自分自身を指すスキーマ
DEFS_REF_SCHEMA = (
    "type: object\n"
    "properties:\n"
    "  entries:\n"
    "    type: array\n"
    "    items: {$ref: '#/$defs/entry'}\n"
    "$defs:\n"
    "  entry:\n"
    "    type: object\n"
    "    properties:\n"
    "      summary: {$ref: 'common.schema.yaml#/$defs/summary'}\n"
    "      children:\n"
    "        type: array\n"
    "        items: {$ref: '#/$defs/entry'}\n"
)
# `$defs.entry` の `summary` が無いファイルを指すスキーマ
MISSING_REF_SCHEMA = DEFS_REF_SCHEMA.replace("common.schema.yaml", "missing.schema.yaml")
# `cwd` の説明を持つ文書の MCP のツール
TOOLS_WITH_CWD = (
    "describe",
    "search_docs",
    "list_match_words",
    "trace_related",
    "list_changes",
    "write_docs",
    "delete_docs",
)
# ツールの入力のスキーマの `cwd` の説明
CWD_DESCRIPTION_TEXT = (
    "作業場所。PreToolUse のフックがセッションの作業場所で上書きするため、指定しても使わない。"
    "ワークツリーを指すときは worktree を指定する"
)
COMMON_SCHEMA = "$defs:\n  summary:\n    type: string\n"
MISSING_REF = "missing.schema.yaml#/$defs/summary"
ENTRIES = [{"summary": "a", "children": [{"summary": "b"}]}]
# 最上位の `tree` が別のファイルの中で循環する定義を指し、中身の違う同じ名前の `$defs.tree` も持つスキーマ
TREE_REF_SCHEMA = (
    "type: object\n"
    "properties:\n"
    "  tree: {$ref: 'common.schema.yaml#/$defs/tree'}\n"
    "$defs:\n"
    "  tree: {type: string}\n"
)
TREE_COMMON_SCHEMA = (
    "$defs:\n"
    "  tree:\n"
    "    type: object\n"
    "    properties:\n"
    "      name: {type: string}\n"
    "      children:\n"
    "        type: array\n"
    "        items: {$ref: '#/$defs/tree'}\n"
)
TREE = {"name": "a", "children": [{"name": "b", "children": [{"name": "c"}]}]}


# `functions`（`$ref` で `x-key: name` の配列）・`x-key` を持たない `steps`・値が文字列の辞書 `notes` を持つスキーマ
REF_PATH_SCHEMA = (
    "type: object\n"
    "title: サンプル\n"
    "properties:\n"
    "  id: {type: string}\n"
    "  name: {type: string}\n"
    "  functions: {$ref: '#/$defs/functions'}\n"
    "  steps:\n"
    "    type: array\n"
    "    items: {type: object}\n"
    "  notes:\n"
    "    type: object\n"
    "    additionalProperties: {type: string}\n"
    "$defs:\n"
    "  functions:\n"
    "    type: array\n"
    "    x-key: name\n"
    "    items:\n"
    "      type: object\n"
    "      properties:\n"
    "        name: {type: string}\n"
    "        process: {type: string}\n"
)
REF_PATH_DOC = (
    "id: doc-1\n"
    "name: 文書 1\n"
    "functions:\n"
    "  - name: load\n"
    "    process: 1 書き出す\n"
    "  - name: save\n"
    "    process: 2 書き出す\n"
    "  - name: save\n"
    "    process: 3 書き出す\n"
    "  - name: items[].name\n"
    "    process: 5 書き出す\n"
    "steps:\n"
    "  - name: a\n"
    "    body: x\n"
    "notes:\n"
    "  main.py の補足: 4 書き出す\n"
    "  a[b]: 6 書き出す\n"
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
    (worktree / "project-index.yaml").write_text(sample_config_text(TERM_ROW), encoding="utf-8")
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


# 関連の要素の `refs` を文字列の並びで持つスキーマ（タグ v1）と、オブジェクトの並びで持つスキーマ（タグ v2）
REF_SCHEMA_V1 = (
    "type: object\n"
    "required: [id]\n"
    "properties:\n"
    "  id: {type: string}\n"
    "  name: {type: string}\n"
    "  refs:\n"
    "    type: array\n"
    "    items: {type: string}\n"
)
REF_SCHEMA_V2 = (
    "type: object\n"
    "required: [id]\n"
    "properties:\n"
    "  id: {type: string}\n"
    "  name: {type: string}\n"
    "  refs:\n"
    "    type: array\n"
    "    items:\n"
    "      type: object\n"
    "      required: [to, type]\n"
    "      properties:\n"
    "        to: {type: string}\n"
    "        type: {type: string}\n"
)


def _ref_config(ref: str) -> str:
    """種類 note のスキーマに、配信元 schemas の `ref` のリビジョンを指す配信元の設定の YAML を作る。"""
    return (
        "name: sample\n"
        "default_ref: develop\n"
        "documents:\n"
        "  - id: note\n"
        "    paths: [notes/*.yaml]\n"
        "    schema:\n"
        "      source: schemas\n"
        "      path: schemas/note.schema.yaml\n"
        f"      ref: {ref}\n"
    )


def test_normal_when_schema_ref_changed_in_worktree(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    run_git: Callable[..., str],
    commit_all: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ワークツリーの設定でスキーマの参照を変えた種類を検査する（正常系）。"""
    # 準備
    schemas = make_source(
        "schemas",
        {
            "project-index.yaml": (
                "name: schemas\ndocuments:\n  - id: note\n    paths: [notes/*.yaml]\n"
                "    schema: schemas/note.schema.yaml\n"
            ),
            "schemas/note.schema.yaml": REF_SCHEMA_V1,
        },
    )
    run_git(schemas.folder, "tag", "v1")
    commit_all(schemas.folder, {"schemas/note.schema.yaml": REF_SCHEMA_V2})
    run_git(schemas.folder, "tag", "v2")
    source = make_source(
        "sample",
        {
            "project-index.yaml": _ref_config("v1"),
            "notes/a.yaml": "id: a\nname: A\n",
            "notes/b.yaml": "id: b\nname: B\n",
        },
    )
    changed = add_worktree(source.folder, "x")
    unchanged = add_worktree(source.folder, "y")
    # ワークツリー x の設定だけ v2 を指し、commit しない
    (changed / "project-index.yaml").write_text(_ref_config("v2"), encoding="utf-8")
    env = make_server(source, schemas)
    # ワークツリーの設定を読み直すときに、参照先の配信元 schemas をこの端末の設定から引かせる
    monkeypatch.setenv("PROJECT_INDEX_CONFIG", str(env.settings_path))
    # クローン本体を指す呼び出しで、起動時の v1 のスキーマを解かせておく
    env.call("search_docs", cwd=str(source.folder), format="json")
    objects = [{"to": "b", "type": "references"}]
    # 実行
    as_objects = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(changed),
        operations=[_update("a", _version(changed / "notes" / "a.yaml"), set={"refs": objects})],
    )
    as_strings = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(changed),
        operations=[_update("a", _version(changed / "notes" / "a.yaml"), set={"refs": ["b"]})],
    )
    in_unchanged = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(unchanged),
        operations=[_update("a", _version(unchanged / "notes" / "a.yaml"), set={"refs": ["b"]})],
    )
    # 検証
    assert not as_objects.is_error
    assert as_objects.data["applied"] is True
    assert as_objects.data["results"][0]["status"] == "updated"
    assert load_yaml((changed / "notes" / "a.yaml").read_text(encoding="utf-8"))["refs"] == objects
    assert as_strings.is_error
    assert "ValidationFailedError" in as_strings.text
    assert "is not of type 'object'" in as_strings.text
    assert not in_unchanged.is_error
    assert in_unchanged.data["applied"] is True
    assert load_yaml((unchanged / "notes" / "a.yaml").read_text(encoding="utf-8"))["refs"] == ["b"]


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


ITEMS_ROWS = (
    "  - id: items\n"
    "    paths: [items/*.yaml]\n"
    "    schema: schemas/items.schema.yaml\n"
    "    write_dates: false\n"
    "  - id: memos\n"
    "    paths: [memos/*.yaml]\n"
    "    schema: schemas/memos.schema.yaml\n"
)
ITEMS_SCHEMA = (
    "type: object\n"
    "additionalProperties: false\n"
    "required: [id, name]\n"
    "properties:\n"
    "  id: {type: string}\n"
    "  name: {type: string}\n"
    "  description: {type: string}\n"
    "  related:\n"
    "    type: array\n"
    "    items:\n"
    "      type: object\n"
    "      properties:\n"
    "        to: {type: string}\n"
    "        type: {type: string}\n"
)
ITEM_1 = "id: i1\nname: I1\ndescription: 旧語\nrelated:\n  - to: m1\n    type: references\n"


def test_normal_when_non_git_source_without_dates(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """`write_dates: false` の種類の文書は、どの操作で書き換えても日時を付けない（正常系）。"""
    # 準備
    sample = make_source("sample")
    memo = make_source(
        "memo",
        sample_file_set(
            **{
                "project-index.yaml": sample_config_text(ITEMS_ROWS, name="memo"),
                "schemas/items.schema.yaml": ITEMS_SCHEMA,
                "schemas/memos.schema.yaml": "type: object\n",
                "items/i1.yaml": ITEM_1,
                "memos/m1.yaml": "id: m1\nname: M1\n",
            }
        ),
        git=False,
        scope_read=[sample.folder],
        scope_write=[sample.folder],
    )
    env = make_server(sample, memo)
    common = {"cwd": str(sample.folder), "source": "memo"}
    items = memo.folder / "items"
    memos = memo.folder / "memos"
    # 実行
    created = env.call(
        "write_docs",
        **common,
        operations=[{"op": "create", "kind": "items", "data": {"id": "i2", "name": "I2"}}],
    )
    updated = env.call(
        "write_docs",
        **common,
        operations=[_update("i1", _version(items / "i1.yaml"), set={"name": "I1b"})],
    )
    replaced = env.call(
        "write_docs",
        **common,
        operations=[
            {
                "op": "replace",
                "id": "i1",
                "expected_version": _version(items / "i1.yaml"),
                "data": load_yaml(ITEM_1),
            }
        ],
    )
    renamed = env.call(
        "write_docs",
        **common,
        operations=[
            {
                "op": "rename",
                "id": "i1",
                "expected_version": _version(items / "i1.yaml"),
                "new_id": "i9",
            }
        ],
    )
    memo_renamed = env.call(
        "write_docs",
        **common,
        operations=[
            {
                "op": "rename",
                "id": "m1",
                "expected_version": _version(memos / "m1.yaml"),
                "new_id": "m9",
            }
        ],
    )
    text_replaced = env.call(
        "write_docs",
        **common,
        operations=[
            {
                "op": "replace_text",
                "filter": {"field": "kind", "op": "eq", "values": ["items"]},
                "old": "旧語",
                "new": "新語",
            }
        ],
    )
    memo_created = env.call(
        "write_docs",
        **common,
        operations=[{"op": "create", "kind": "memos", "data": {"id": "m2", "name": "M2"}}],
    )
    # 検証
    results = [created, updated, replaced, renamed, memo_renamed, text_replaced, memo_created]
    assert [result.is_error for result in results] == [False] * 7
    assert [result.data["applied"] for result in results] == [True] * 7
    assert all(row["status"] != "failed" for result in results for row in result.data["results"])
    item_2 = load_yaml((items / "i2.yaml").read_text(encoding="utf-8"))
    item_9 = load_yaml((items / "i9.yaml").read_text(encoding="utf-8"))
    memo_9 = load_yaml((memos / "m9.yaml").read_text(encoding="utf-8"))
    memo_2 = load_yaml((memos / "m2.yaml").read_text(encoding="utf-8"))
    assert sorted(item_2) == ["id", "name"]
    assert sorted(item_9) == ["description", "id", "name", "related"]
    assert item_9["description"] == "新語"
    assert item_9["related"] == [{"to": "m9", "type": "references"}]
    assert memo_9["updated"]
    assert memo_2["created"]
    assert memo_2["updated"]


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


def test_error_when_target_is_clone_and_config_in_worktree(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
) -> None:
    """配信元の設定をワークツリーから読んでいても、返すクローン本体のパスはワークツリーの親のクローン本体（異常系）。"""
    # 準備
    source = make_source("sample")
    worktree_y = add_worktree(source.folder, "y")
    env = make_server(
        replace(
            source,
            config=[worktree_y / "project-index.yaml"],
            scope_write=[source.folder],
        )
    )
    clone_target = source.folder / "docs" / "doc-1.yaml"
    worktree_target = worktree_y / "docs" / "doc-1.yaml"
    clone_before = clone_target.read_text(encoding="utf-8")
    worktree_before = worktree_target.read_text(encoding="utf-8")
    # 実行
    result = env.call(
        "write_docs",
        source="sample",
        cwd=str(source.folder),
        operations=[_update("doc-1", _version(clone_target), set={"name": "新しい名前"})],
    )
    # 検証
    assert result.is_error
    assert "TargetIsCloneError" in result.text
    assert f"{source.folder} はクローン本体です" in result.text
    assert str(worktree_y) not in result.text
    assert clone_target.read_text(encoding="utf-8") == clone_before
    assert worktree_target.read_text(encoding="utf-8") == worktree_before


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


def _edit(field: str) -> dict[str, str]:
    """`書き出す` を `保存する` に置き換える `text_edits` の 1 件を作る。"""
    return {"field": field, "old": "書き出す", "new": "保存する"}


def test_normal_when_text_edits_ref_path(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """参照の型の項目のパスで、x-key の値で指した配列の要素の中の文字列の一部を置き換える（正常系）。"""
    # 準備
    files = sample_file_set(
        **{"schemas/sample.schema.yaml": REF_PATH_SCHEMA, "docs/doc-1.yaml": REF_PATH_DOC}
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    path = worktree / "docs" / "doc-1.yaml"
    arguments = {"cwd": str(source.folder), "worktree": str(worktree)}
    # 実行
    first = env.call(
        "write_docs",
        operations=[
            _update("doc-1", _version(path), text_edits=[_edit("#functions[save].process")])
        ],
        **arguments,
    )
    after_first = load_yaml(path.read_text(encoding="utf-8"))
    second = env.call(
        "write_docs",
        operations=[
            _update("doc-1", _version(path), text_edits=[_edit("#functions[save#2].process")])
        ],
        **arguments,
    )
    after_second = load_yaml(path.read_text(encoding="utf-8"))
    before_third = path.read_text(encoding="utf-8")
    third = env.call(
        "write_docs",
        operations=[
            _update("doc-1", _version(path), text_edits=[_edit("functions[save].process")])
        ],
        **arguments,
    )
    after_third = path.read_text(encoding="utf-8")
    fourth = env.call(
        "write_docs",
        operations=[_update("doc-1", _version(path), text_edits=[_edit("#notes[main.py の補足]")])],
        **arguments,
    )
    after_fourth = load_yaml(path.read_text(encoding="utf-8"))
    fifth = env.call(
        "write_docs",
        operations=[
            _update("doc-1", _version(path), text_edits=[_edit("#functions[items[].name].process")])
        ],
        **arguments,
    )
    after_fifth = load_yaml(path.read_text(encoding="utf-8"))
    sixth = env.call(
        "write_docs",
        operations=[_update("doc-1", _version(path), text_edits=[_edit("#notes[a[b]]")])],
        **arguments,
    )
    after_sixth = load_yaml(path.read_text(encoding="utf-8"))
    # 検証
    assert [item["status"] for item in first.data["results"]] == ["updated"]
    assert [item["process"] for item in after_first["functions"]] == [
        "1 書き出す",
        "2 保存する",
        "3 書き出す",
        "5 書き出す",
    ]
    assert [item["status"] for item in second.data["results"]] == ["updated"]
    assert [item["process"] for item in after_second["functions"]] == [
        "1 書き出す",
        "2 保存する",
        "3 保存する",
        "5 書き出す",
    ]
    assert third.is_error
    assert "text_edits[0].field" in third.text
    assert "文字列ではない項目は置き換えられません" in third.text
    # fix: x-key の値で指す書き方・位置で指す書き方・配列とオブジェクトを書き換える操作
    assert "#functions[save].process" in third.text
    assert "flows[35].expected[2]" in third.text
    assert "`set`・`add_to`・`remove_from`" in third.text
    assert after_third == before_third
    assert [item["status"] for item in fourth.data["results"]] == ["updated"]
    assert after_fourth["notes"] == {"main.py の補足": "4 保存する", "a[b]": "6 書き出す"}
    assert [item["status"] for item in fifth.data["results"]] == ["updated"]
    assert [item["process"] for item in after_fifth["functions"]] == [
        "1 書き出す",
        "2 保存する",
        "3 保存する",
        "5 保存する",
    ]
    assert [item["status"] for item in sixth.data["results"]] == ["updated"]
    assert after_sixth["notes"] == {"main.py の補足": "4 保存する", "a[b]": "6 保存する"}


@pytest.mark.parametrize(
    ("field", "message"),
    [
        pytest.param("#steps[a].body", "x-key を持たない配列です", id="no_x_key"),
        pytest.param(
            "#functions[missing].process", "name が missing の要素がありません", id="missing"
        ),
        pytest.param("#functions[save#3].process", "name が save の要素は 2 個です", id="order"),
        pytest.param("#notes[missing]", "キー missing がありません", id="no_key"),
        pytest.param(
            "#functions[save[1].process", "記載方法が誤っています", id="unbalanced_brackets"
        ),
    ],
)
def test_error_when_text_edits_ref_path_unresolved(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    field: str,
    message: str,
) -> None:
    """x-key の無い配列・該当する要素の無い値・無い順番・無いキーを指すパスと、`[...]` の中の `[` `]` の対応が取れない参照の型の項目のパスを断る（異常系）。"""
    # 準備
    files = sample_file_set(
        **{"schemas/sample.schema.yaml": REF_PATH_SCHEMA, "docs/doc-1.yaml": REF_PATH_DOC}
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    path = worktree / "docs" / "doc-1.yaml"
    before = path.read_text(encoding="utf-8")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[_update("doc-1", _version(path), text_edits=[_edit(field)])],
    )
    # 検証
    assert result.is_error
    assert "text_edits[0].field" in result.text
    assert message in result.text
    # fix: x-key の値で指す書き方・位置で指す書き方・配列とオブジェクトを書き換える操作
    assert "#functions[save].process" in result.text
    assert "flows[35].expected[2]" in result.text
    assert "`set`・`add_to`・`remove_from`" in result.text
    assert path.read_text(encoding="utf-8") == before


MODELS_SCHEMA = (
    "type: object\n"
    "title: サンプル\n"
    "properties:\n"
    "  id: {type: string}\n"
    "  name: {type: string}\n"
    "  models:\n"
    "    type: array\n"
    "    x-key: name\n"
    "    items:\n"
    "      type: object\n"
    "      properties:\n"
    "        name: {type: string}\n"
    "        properties:\n"
    "          type: array\n"
    "          items: {type: string}\n"
)
MODELS_DOC = (
    "id: doc-1\n"
    "name: 文書 1\n"
    "models:\n"
    "  - name: Row\n"
    "    properties: [a]\n"
    "  - name: Col\n"
    "    properties: [b]\n"
)


def test_normal_when_add_to_ref_path(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """add_to・remove_from のキーの参照の型の項目のパスで、x-key の値で指した要素の中の配列へ追加・削除し、unset の要素の参照の型の項目のパスで項目を削除する（正常系）。"""
    # 準備
    files = sample_file_set(
        **{"schemas/sample.schema.yaml": MODELS_SCHEMA, "docs/doc-1.yaml": MODELS_DOC}
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    path = worktree / "docs" / "doc-1.yaml"
    arguments = {"cwd": str(source.folder), "worktree": str(worktree)}

    def _call(**operation: Any) -> Any:
        return env.call(
            "write_docs", operations=[_update("doc-1", _version(path), **operation)], **arguments
        )

    # 実行
    first = _call(add_to={"#models[Row].properties": ["c"]})
    after_first = load_yaml(path.read_text(encoding="utf-8"))
    second = _call(remove_from={"#models[Row].properties": ["a"]})
    after_second = load_yaml(path.read_text(encoding="utf-8"))
    before_errors = path.read_text(encoding="utf-8")
    third = _call(add_to={"models[Row].properties": ["d"]})
    fourth = _call(add_to={"#models[Zzz].properties": ["d"]})
    fifth = _call(add_to={"#models[Row].name": ["d"]})
    after_errors = path.read_text(encoding="utf-8")
    sixth = _call(unset=["#models[Col].properties"])
    after_sixth = load_yaml(path.read_text(encoding="utf-8"))
    before_unset_errors = path.read_text(encoding="utf-8")
    seventh = _call(unset=["models[Row].properties"])
    eighth = _call(unset=["#models[Zzz].properties"])
    after_unset_errors = path.read_text(encoding="utf-8")
    # 検証
    assert [item["status"] for item in first.data["results"]] == ["updated"]
    assert after_first["models"] == [
        {"name": "Row", "properties": ["a", "c"]},
        {"name": "Col", "properties": ["b"]},
    ]
    assert [item["status"] for item in second.data["results"]] == ["updated"]
    assert after_second["models"] == [
        {"name": "Row", "properties": ["c"]},
        {"name": "Col", "properties": ["b"]},
    ]
    assert third.is_error
    assert "operations[0].add_to.models[Row].properties" in third.text
    assert fourth.is_error
    assert "operations[0].add_to.#models[Zzz].properties" in fourth.text
    assert fifth.is_error
    assert "operations[0].add_to.#models[Row].name" in fifth.text
    assert after_errors == before_errors
    assert [item["status"] for item in sixth.data["results"]] == ["updated"]
    assert after_sixth["models"] == [
        {"name": "Row", "properties": ["c"]},
        {"name": "Col"},
    ]
    assert seventh.is_error
    assert "operations[0].unset.models[Row].properties" in seventh.text
    assert eighth.is_error
    assert "operations[0].unset.#models[Zzz].properties" in eighth.text
    assert after_unset_errors == before_unset_errors


SET_SCHEMA = (
    "type: object\n"
    "title: サンプル\n"
    "properties:\n"
    "  id: {type: string}\n"
    "  name: {type: string}\n"
    "  models:\n"
    "    type: array\n"
    "    x-key: name\n"
    "    items:\n"
    "      type: object\n"
    "      properties:\n"
    "        name: {type: string}\n"
    "        properties:\n"
    "          type: array\n"
    "          items: {type: string}\n"
    "        label: {type: string}\n"
    "        meta: {type: object}\n"
    "  steps:\n"
    "    type: array\n"
    "    items:\n"
    "      type: object\n"
    "      properties:\n"
    "        name: {type: string}\n"
    "        body: {type: string}\n"
    "  notes:\n"
    "    type: object\n"
    "    additionalProperties: {type: string}\n"
)
SET_DOC = (
    "id: doc-1\n"
    "name: 文書 1\n"
    "models:\n"
    "  - name: Row\n"
    "    properties: [a]\n"
    "    meta:\n"
    "      x: 1\n"
    "  - name: Col\n"
    "    properties: [b]\n"
    "steps:\n"
    "  - name: a\n"
    "    body: x\n"
    "notes:\n"
    "  main: m\n"
)


def test_normal_when_set_ref_path(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """set のキーの参照の型の項目のパスで、x-key の値で指した要素に今は無いキーを追加し、解決できないキーを断る（正常系）。"""
    # 準備
    files = sample_file_set(
        **{"schemas/sample.schema.yaml": SET_SCHEMA, "docs/doc-1.yaml": SET_DOC}
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    path = worktree / "docs" / "doc-1.yaml"
    arguments = {"cwd": str(source.folder), "worktree": str(worktree)}

    def _call(**operation: Any) -> Any:
        return env.call(
            "write_docs", operations=[_update("doc-1", _version(path), **operation)], **arguments
        )

    # 実行
    before_first = path.read_text(encoding="utf-8").splitlines()
    first = _call(set={"#models[Col].label": "l"})
    after_first_lines = path.read_text(encoding="utf-8").splitlines()
    second = _call(set={"#models[Col].label": "m"})
    third = _call(set={"#models[Row].meta": {"y": 2}})
    after_third = load_yaml(path.read_text(encoding="utf-8"))
    before_errors = path.read_text(encoding="utf-8")
    fourth = _call(set={"models[Col].label": "n"})
    fifth = _call(set={"#models[Zzz].label": "n"})
    sixth = _call(set={"#steps[a].body": "n"})
    seventh = _call(set={"#models[Col#2].label": "n"})
    eighth = _call(set={"#models[Col].other.label": "n"})
    after_errors = path.read_text(encoding="utf-8")
    ninth = _call(set={"#notes[a.b]": "v"})
    after_ninth = load_yaml(path.read_text(encoding="utf-8"))
    # 検証
    assert [item["status"] for item in first.data["results"]] == ["updated"]
    assert [line for line in after_first_lines if line not in before_first] == ["    label: l"]
    assert len(after_first_lines) == len(before_first) + 1
    assert [item["status"] for item in second.data["results"]] == ["updated"]
    assert [item["status"] for item in third.data["results"]] == ["updated"]
    assert after_third["models"] == [
        {"name": "Row", "properties": ["a"], "meta": {"x": 1, "y": 2}},
        {"name": "Col", "properties": ["b"], "label": "m"},
    ]
    assert fourth.is_error
    assert "operations[0].set.models[Col].label" in fourth.text
    assert "`#` で始めて x-key の値で要素を指してください" in fourth.text
    assert fifth.is_error
    assert "operations[0].set.#models[Zzz].label" in fifth.text
    assert "name が Zzz の要素がありません" in fifth.text
    assert sixth.is_error
    assert "x-key を持たない配列です" in sixth.text
    assert seventh.is_error
    assert "name が Col の要素は 1 個です" in seventh.text
    assert eighth.is_error
    assert "にキー other がありません" in eighth.text
    assert after_errors == before_errors
    assert [item["status"] for item in ninth.data["results"]] == ["updated"]
    assert after_ninth["notes"] == {"main": "m", "a.b": "v"}


FLOWS_SCHEMA = (
    "type: object\n"
    "title: サンプル\n"
    "properties:\n"
    "  id: {type: string}\n"
    "  name: {type: string}\n"
    "  flows:\n"
    "    type: array\n"
    "    x-key: name\n"
    "    items:\n"
    "      type: object\n"
    "      properties:\n"
    "        name: {type: string}\n"
    "        summary: {type: string}\n"
    "  notes:\n"
    "    type: array\n"
    "    items: {type: string}\n"
)
FLOWS_DOC = (
    "id: doc-1\n"
    "name: 文書 1\n"
    "flows:\n"
    "  - name: 正常系\n"
    "    summary: s1\n"
    "  - name: 異常系\n"
    "    summary: s2\n"
    "  - name: 準正常系\n"
    "    summary: s3\n"
    "notes: [a]\n"
)


def test_normal_when_remove_from_x_key(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """remove_from で x-key を持つ配列の要素を x-key の値と要素のオブジェクトで指して削除し、削除する要素が無い値を断る。同じ操作の add_to は remove_from の後に当てる（正常系）。"""
    # 準備
    files = sample_file_set(
        **{"schemas/sample.schema.yaml": FLOWS_SCHEMA, "docs/doc-1.yaml": FLOWS_DOC}
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    path = worktree / "docs" / "doc-1.yaml"
    arguments = {"cwd": str(source.folder), "worktree": str(worktree)}

    def _call(**operation: Any) -> Any:
        return env.call(
            "write_docs", operations=[_update("doc-1", _version(path), **operation)], **arguments
        )

    # 実行
    version_before = _version(path)
    first = _call(remove_from={"flows": ["異常系"]})
    after_first = load_yaml(path.read_text(encoding="utf-8"))
    second = _call(remove_from={"flows": [{"name": "準正常系", "summary": "s3"}]})
    after_second = load_yaml(path.read_text(encoding="utf-8"))
    before_error = path.read_text(encoding="utf-8")
    third = _call(remove_from={"flows": ["正常系", "無い名前"]})
    after_error = path.read_text(encoding="utf-8")
    fourth = _call(remove_from={"notes": ["z"]})
    after_fourth = load_yaml(path.read_text(encoding="utf-8"))
    fifth = _call(
        remove_from={"flows": ["正常系", {"name": "正常系", "summary": "s1"}]},
        add_to={"flows": [{"name": "正常系", "summary": "s9"}]},
    )
    after_fifth = load_yaml(path.read_text(encoding="utf-8"))
    # 検証
    assert [item["status"] for item in first.data["results"]] == ["updated"]
    assert first.data["results"][0]["version"] != version_before
    assert after_first["flows"] == [
        {"name": "正常系", "summary": "s1"},
        {"name": "準正常系", "summary": "s3"},
    ]
    assert [item["status"] for item in second.data["results"]] == ["updated"]
    assert after_second["flows"] == [{"name": "正常系", "summary": "s1"}]
    assert third.is_error
    assert "operations[0].remove_from.flows" in third.text
    assert "無い名前" in third.text
    assert after_error == before_error
    assert [item["status"] for item in fourth.data["results"]] == ["updated"]
    assert after_fourth["notes"] == ["a"]
    assert [item["status"] for item in fifth.data["results"]] == ["updated"]
    assert after_fifth["flows"] == [{"name": "正常系", "summary": "s9"}]


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
    """create で決めた配置先のファイル名が exclude に当たるとき、何も書かずに断る（異常系）。"""
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


def test_error_when_placement_undecided(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """records を持つ行の paths の先頭が glob のとき、create の配置先を決められず、何も書き込まずに断る（異常系）。"""
    # 準備
    items_row = (
        "  - id: items\n"
        "    paths: [data/*.yaml]\n"
        "    schema: schemas/sample.schema.yaml\n"
        "    records: items\n"
    )
    files = sample_file_set(**{"project-index.yaml": sample_config_text(items_row)})
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[{"op": "create", "kind": "items", "id": "item-1", "data": {"name": "要素 1"}}],
    )
    # 検証
    assert result.is_error
    assert "InvalidArgumentError" in result.text
    assert "operations[0].kind" in result.text
    assert "items の新しい文書の配置先を決められません" in result.text
    assert "documents[].paths の先頭を glob を含まない 1 つのファイルにしてください" in result.text
    assert not (worktree / "data").exists()


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
    """ツールの説明に、範囲のファイルの作成・削除・改名で管理用の YAML の行を修正することと、`cwd` は指定しても使わず `worktree` でワークツリーを指すことを含める（正常系）。"""
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
    cwd_descriptions = {
        name: tools[name]["inputSchema"]["properties"]["cwd"]["description"]
        for name in TOOLS_WITH_CWD
    }
    assert cwd_descriptions == dict.fromkeys(TOOLS_WITH_CWD, CWD_DESCRIPTION_TEXT)


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


UNINDENTED_ITEMS_DOC = (
    "id: doc-1\nname: 文書 1\nitems:\n- key: k1\n  label: 名称 1\n- key: k2\n  label: 名称 2\n"
)
INDENTED_ITEMS_DOC = (
    "id: doc-2\nname: 文書 2\nitems:\n  - key: k1\n    label: 名称 1\n"
    "  - key: k2\n    label: 名称 2\n"
)


def test_normal_when_indent_preserved(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """書き換えた文書の、変更していない行の字下げを元のまま書き出す（正常系）。"""
    # 準備
    files = sample_file_set(
        **{"docs/doc-1.yaml": UNINDENTED_ITEMS_DOC, "docs/doc-2.yaml": INDENTED_ITEMS_DOC}
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    added = {"items": [{"key": "k3", "label": "名称 3"}]}
    results: dict[str, Any] = {}
    # 実行
    for doc_id in ("doc-1", "doc-2"):
        target = worktree / "docs" / f"{doc_id}.yaml"
        results[doc_id] = env.call(
            "write_docs",
            cwd=str(source.folder),
            worktree=str(worktree),
            operations=[_update(doc_id, _version(target), add_to=added)],
        )
    # 検証
    assert (worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8") == (
        UNINDENTED_ITEMS_DOC + "- key: k3\n  label: 名称 3\n"
    )
    assert (worktree / "docs" / "doc-2.yaml").read_text(encoding="utf-8") == (
        INDENTED_ITEMS_DOC + "  - key: k3\n    label: 名称 3\n"
    )
    assert results["doc-1"].data["results"][0]["diff"] == "+ - key: k3\n+   label: 名称 3"
    assert results["doc-2"].data["results"][0]["diff"] == "+   - key: k3\n+     label: 名称 3"


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


def test_normal_when_relative_ref_in_defs(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """$defs の中の相対パスの参照を解決して検査し、部分更新を書き込む（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "schemas/sample.schema.yaml": DEFS_REF_SCHEMA,
            "schemas/common.schema.yaml": COMMON_SCHEMA,
            "docs/doc-1.yaml": sample_doc_text(
                "doc-1", "文書 1", description="1 件目", entries=ENTRIES
            ),
        }
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    target = worktree / "docs" / "doc-1.yaml"
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[
            _update(
                "doc-1",
                _version(target),
                text_edits=[{"field": "description", "old": "1 件目", "new": "一件目"}],
            )
        ],
    )
    # 検証
    assert not result.is_error
    assert result.data["applied"] is True
    assert result.data["results"][0]["status"] == "updated"
    assert load_yaml(target.read_text(encoding="utf-8"))["description"] == "一件目"


def test_normal_when_cyclic_ref_in_other_file(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """別のファイルの中で循環する参照をそのファイルの定義を指したまま検査し、部分更新を書き込む（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "schemas/sample.schema.yaml": TREE_REF_SCHEMA,
            "schemas/common.schema.yaml": TREE_COMMON_SCHEMA,
            "docs/doc-1.yaml": sample_doc_text("doc-1", "文書 1", description="1 件目", tree=TREE),
        }
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    target = worktree / "docs" / "doc-1.yaml"
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[
            _update(
                "doc-1",
                _version(target),
                text_edits=[{"field": "description", "old": "1 件目", "new": "一件目"}],
            )
        ],
    )
    # 検証
    assert not result.is_error
    assert result.data["applied"] is True
    assert result.data["results"][0]["status"] == "updated"
    assert load_yaml(target.read_text(encoding="utf-8"))["description"] == "一件目"


def test_error_when_schema_ref_unresolvable(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """スキーマの参照を解決できないときは、解決できなかった参照を違反として返し、何も書かない（異常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "schemas/sample.schema.yaml": MISSING_REF_SCHEMA,
            "docs/doc-1.yaml": sample_doc_text(
                "doc-1", "文書 1", description="1 件目", entries=ENTRIES
            ),
        }
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    target = worktree / "docs" / "doc-1.yaml"
    before = target.read_text(encoding="utf-8")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[
            _update(
                "doc-1",
                _version(target),
                text_edits=[{"field": "description", "old": "1 件目", "new": "一件目"}],
            )
        ],
    )
    # 検証
    assert result.is_error
    assert "ValidationFailedError" in result.text
    assert "operations[0]" in result.text
    assert MISSING_REF in result.text
    assert "schemas/sample.schema.yaml" in result.text
    assert target.read_text(encoding="utf-8") == before


def _slow_validator_files(
    sample_file_set: Callable[..., dict[str, str]], wait_sec: int
) -> dict[str, str]:
    """`wait_sec` 秒待ってから違反なしで終わる検査のスクリプト `slow` を持つ配信元のファイル一式。"""
    config = (
        "name: sample\n"
        "default_ref: develop\n"
        "documents:\n"
        "  - id: sample\n"
        "    paths: [docs/*.yaml]\n"
        "    schema: schemas/sample.schema.yaml\n"
        "    validators: [slow]\n"
        "validators:\n"
        "  - id: slow\n"
        "    run: [python3, scripts/slow.py]\n"
    )
    script = f"import sys, time\nsys.stdin.read()\ntime.sleep({wait_sec})\nprint('[]')\n"
    return sample_file_set(**{"project-index.yaml": config, "scripts/slow.py": script})


def test_error_when_write_deadline_exceeded(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """検査が書き込みの期限までに終了しなければ、検査のスクリプトを止めて、何も書き込まずに時間切れを返却する（異常系）。"""
    # 準備
    source = make_source("sample", _slow_validator_files(sample_file_set, 4))
    worktree = add_worktree(source.folder, "x")
    env = make_server(source, settings_extra="write_deadline_sec: 2\n")
    target = worktree / "docs" / "doc-1.yaml"
    before_text = target.read_text(encoding="utf-8")
    before = _version(target)
    # 実行
    started = time.monotonic()
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[_update("doc-1", before, set={"name": "新しい名前"})],
    )
    elapsed = time.monotonic() - started
    time.sleep(4)
    searched = env.call(
        "search_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        filter={"field": "id", "op": "eq", "values": ["doc-1"]},
        format="json",
    )
    # 検証
    assert result.is_error is True
    assert result.text.startswith("WriteDeadlineExceededError: 書き込みの期限（2 秒）を超えたため")
    assert "ファイルを書き換えずに止めました" in result.text
    assert elapsed < 3
    assert target.read_text(encoding="utf-8") == before_text
    assert searched.data["items"][0]["values"]["version"] == before


def test_error_when_validator_timed_out(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """`validators[]` のスクリプトが `script_timeout_sec` を超えたら止め、止めたスクリプトの ID を違反として返却する（異常系）。"""
    # 準備
    source = make_source("sample", _slow_validator_files(sample_file_set, 5))
    worktree = add_worktree(source.folder, "x")
    env = make_server(source, settings_extra="script_timeout_sec: 1\n")
    target = worktree / "docs" / "doc-1.yaml"
    before_text = target.read_text(encoding="utf-8")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        operations=[_update("doc-1", _version(target), set={"name": "新しい名前"})],
    )
    # 検証
    assert result.is_error is True
    assert result.text.startswith("ValidationFailedError:")
    assert not result.text.startswith("Error executing tool")
    assert (
        "slow: 検査を実行できませんでした（制限時間（1 秒）を超えたため、スクリプトを止めました。）"
        in result.text
    )
    assert target.read_text(encoding="utf-8") == before_text


NOTES_ROW = (
    "  - id: notes\n"
    "    paths: [notes/index.yaml]\n"
    "    schema: schemas/notes.schema.yaml\n"
    "    records: items\n"
    "    body_file: path\n"
)
NOTES_SCHEMA = (
    "type: object\n"
    "properties:\n"
    "  items:\n"
    "    type: array\n"
    "    items:\n"
    "      type: object\n"
    "      properties:\n"
    "        id: {type: string}\n"
    "        path: {type: string}\n"
)
NOTES = "items:\n  - id: n1\n    path: n1.md\n"
NOTE_1 = "# n1\n古い行\n"


def _notes_files(
    sample_file_set: Callable[..., dict[str, str]], sample_config_text: Callable[..., str]
) -> dict[str, str]:
    """本文のファイルを持つ行 `notes` と、sample の文書を持つ配信元のファイル一式を返す。"""
    return sample_file_set(
        **{
            "project-index.yaml": sample_config_text(NOTES_ROW),
            "schemas/notes.schema.yaml": NOTES_SCHEMA,
            "notes/index.yaml": NOTES,
            "notes/n1.md": NOTE_1,
        }
    )


def test_normal_when_body_file(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """`records`・`body_file` の行で、要素と本文のファイルを作成・一部の置き換え・全体の置き換えをする（正常系）。"""
    # 準備
    files = _notes_files(sample_file_set, sample_config_text)
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    n1_version = value_hash([{"id": "n1", "path": "n1.md"}, NOTE_1])
    edit = _update(
        "n1", n1_version, text_edits=[{"field": "@body", "old": "古い行", "new": "新しい行"}]
    )
    common = {"cwd": str(source.folder), "worktree": str(worktree)}
    # 実行
    created = env.call(
        "write_docs",
        **common,
        operations=[
            {
                "op": "create",
                "kind": "notes",
                "data": {"id": "n2", "path": "n2.md", "@body": "本文\n"},
            }
        ],
    )
    created_text = (worktree / "notes" / "n2.md").read_text(encoding="utf-8")
    tried = env.call("write_docs", **common, operations=[edit], dry_run=True)
    tried_text = (worktree / "notes" / "n1.md").read_text(encoding="utf-8")
    edited = env.call("write_docs", **common, operations=[edit])
    searched = env.call(
        "search_docs",
        **common,
        filter={"field": "id", "op": "eq", "values": ["n1"]},
        format="json",
    )
    stale = env.call("write_docs", **common, operations=[edit])
    replaced = env.call(
        "write_docs",
        **common,
        operations=[
            _update("n2", created.data["results"][0]["version"], set={"@body": "置き換えた本文\n"})
        ],
    )
    # 検証
    index = load_yaml((worktree / "notes" / "index.yaml").read_text(encoding="utf-8"))
    assert not created.is_error
    assert index["items"] == [{"id": "n1", "path": "n1.md"}, {"id": "n2", "path": "n2.md"}]
    assert created_text == "本文\n"
    assert tried.data["applied"] is False
    assert "@@ notes/n1.md" in tried.data["results"][0]["diff"]
    assert "新しい行" in tried.data["results"][0]["diff"]
    assert tried_text == NOTE_1
    assert not edited.is_error
    assert edited.data["results"][0]["version"] != n1_version
    assert searched.data["items"][0]["values"]["version"] == edited.data["results"][0]["version"]
    assert (worktree / "notes" / "n1.md").read_text(encoding="utf-8") == "# n1\n新しい行\n"
    assert stale.is_error
    assert "VersionMismatchError" in stale.text
    assert not replaced.is_error
    assert (worktree / "notes" / "n2.md").read_text(encoding="utf-8") == "置き換えた本文\n"


ABSENT_NOTES = "items:\n  - id: n1\n    path: n1.md\n  - id: n3\n  - id: n5\n"


def _absent_files(
    sample_file_set: Callable[..., dict[str, str]], sample_config_text: Callable[..., str]
) -> dict[str, str]:
    """本文のファイルを持つ n1 と、持たない n3・n5 の行 `notes` と、n5 を指す文書 1 を持つ配信元のファイル一式を返す。"""
    return {
        **_notes_files(sample_file_set, sample_config_text),
        "notes/index.yaml": ABSENT_NOTES,
        "docs/doc-1.yaml": (
            "id: doc-1\nname: 文書 1\nrelated:\n  - to: n5\n    type: references\n"
        ),
    }


def _note_files(worktree: Path) -> list[str]:
    """ワークツリーの `notes/` のファイル名を並べて返す。"""
    return sorted(path.name for path in (worktree / "notes").iterdir())


def test_normal_when_body_file_absent(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """`body_file` の列を持たない要素を作成・更新・改名し、後から本文のファイルを付ける（正常系）。"""
    # 準備
    files = _absent_files(sample_file_set, sample_config_text)
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    common = {"cwd": str(source.folder), "worktree": str(worktree)}
    before = _note_files(worktree)
    # 実行
    created = env.call(
        "write_docs", **common, operations=[{"op": "create", "kind": "notes", "data": {"id": "n4"}}]
    )
    after_create = (
        _note_files(worktree),
        (worktree / "notes" / "index.yaml").read_text(encoding="utf-8"),
    )
    titled = env.call(
        "write_docs",
        **common,
        operations=[_update("n3", value_hash({"id": "n3"}), set={"title": "t"})],
    )
    after_title = (
        _note_files(worktree),
        (worktree / "notes" / "index.yaml").read_text(encoding="utf-8"),
    )
    bodied = env.call(
        "write_docs",
        **common,
        operations=[
            _update(
                "n3",
                titled.data["results"][0]["version"],
                set={"path": "n3.md", "@body": "本文\n"},
            )
        ],
    )
    after_body = _note_files(worktree)
    renamed = env.call(
        "write_docs",
        **common,
        operations=[
            {
                "op": "rename",
                "id": "n5",
                "expected_version": value_hash({"id": "n5"}),
                "new_id": "n9",
            }
        ],
    )
    # 検証
    assert not created.is_error
    assert created.data["results"][0]["id"] == "n4"
    assert after_create[0] == before
    assert load_yaml(after_create[1])["items"][-1] == {"id": "n4"}
    assert not titled.is_error
    assert after_title[0] == before
    assert load_yaml(after_title[1])["items"][1] == {"id": "n3", "title": "t"}
    assert not bodied.is_error
    assert "@@ notes/n3.md" in bodied.data["results"][0]["diff"]
    assert (worktree / "notes" / "n3.md").read_text(encoding="utf-8") == "本文\n"
    assert not renamed.is_error
    index = load_yaml((worktree / "notes" / "index.yaml").read_text(encoding="utf-8"))
    assert index["items"] == [
        {"id": "n1", "path": "n1.md"},
        {"id": "n3", "title": "t", "path": "n3.md"},
        {"id": "n9"},
        {"id": "n4"},
    ]
    doc_1 = load_yaml((worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8"))
    assert doc_1["related"] == [{"to": "n9", "type": "references"}]
    assert _note_files(worktree) == after_body


def test_error_when_body_without_body_file(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """本文のファイルの有無を片方だけで切り替える操作と、本文のファイルを持たない要素への `new_path` を断る（異常系）。"""
    # 準備
    files = _absent_files(sample_file_set, sample_config_text)
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    common = {"cwd": str(source.folder), "worktree": str(worktree)}
    n3 = value_hash({"id": "n3"})
    n1 = value_hash([{"id": "n1", "path": "n1.md"}, NOTE_1])
    operations = [
        {"op": "create", "kind": "notes", "data": {"id": "n6", "@body": "本文\n"}},
        _update("n3", n3, set={"@body": "本文\n"}),
        _update("n3", n3, set={"path": "n3.md"}),
        _update("n3", n3, text_edits=[{"field": "@body", "old": "a", "new": "b"}]),
        {"op": "rename", "id": "n3", "expected_version": n3, "new_path": "notes/n7.md"},
        _update("n1", n1, unset=["path"]),
        {"op": "replace", "id": "n1", "expected_version": n1, "data": {"id": "n1"}},
    ]
    # 実行
    results = [env.call("write_docs", **common, operations=[operation]) for operation in operations]
    # 検証
    assert [result.is_error for result in results] == [True] * 7
    assert ["InvalidArgumentError" in result.text for result in results] == [True] * 7
    assert [
        path in result.text
        for path, result in zip(
            [
                "operations[0].data.path",
                "operations[0].set.path",
                "operations[0].set.@body",
                "operations[0].text_edits[0].field",
                "operations[0].new_path",
                "operations[0].unset.path",
                "operations[0].data.path",
            ],
            results,
            strict=True,
        )
    ] == [True] * 7
    assert (worktree / "notes" / "index.yaml").read_text(encoding="utf-8") == ABSENT_NOTES
    assert (worktree / "notes" / "n1.md").read_text(encoding="utf-8") == NOTE_1
    assert _note_files(worktree) == ["index.yaml", "n1.md"]


def test_error_when_body_file_outside_source(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """配信元の外へ解かれる本文のファイルのパスの `create` を断り、何も書かない（異常系）。"""
    # 準備
    files = _notes_files(sample_file_set, sample_config_text)
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    common = {"cwd": str(source.folder), "worktree": str(worktree)}
    n4 = {"op": "create", "kind": "notes", "data": {"id": "n4", "path": "n4.md", "@body": "本文\n"}}
    # 実行
    outside = env.call(
        "write_docs",
        **common,
        operations=[
            {
                "op": "create",
                "kind": "notes",
                "data": {"id": "n3", "path": "../../outside/n3.md", "@body": "本文\n"},
            },
            n4,
        ],
    )
    existing = env.call(
        "write_docs",
        **common,
        operations=[
            {
                "op": "create",
                "kind": "notes",
                "data": {"id": "n3", "path": "n1.md", "@body": "本文\n"},
            }
        ],
    )
    # 検証
    assert outside.is_error
    assert "ValidationFailedError" in outside.text
    assert "operations[0].path" in outside.text
    assert existing.is_error
    assert "operations[0].path" in existing.text
    assert (worktree / "notes" / "index.yaml").read_text(encoding="utf-8") == NOTES
    assert (worktree / "notes" / "n1.md").read_text(encoding="utf-8") == NOTE_1
    assert not (worktree / "notes" / "n4.md").exists()
    assert not (worktree.parent / "outside").exists()


def test_error_when_body_not_accepted(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """`@body` を受けられない操作と、`body_file` の列の値を変える操作を断る（異常系）。"""
    # 準備
    files = _notes_files(sample_file_set, sample_config_text)
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    common = {"cwd": str(source.folder), "worktree": str(worktree)}
    doc_1 = worktree / "docs" / "doc-1.yaml"
    doc_1_before = doc_1.read_text(encoding="utf-8")
    n1_version = value_hash([{"id": "n1", "path": "n1.md"}, NOTE_1])
    # 実行
    no_body_file = env.call(
        "write_docs", **common, operations=[_update("doc-1", _version(doc_1), set={"@body": "x"})]
    )
    without_body = env.call(
        "write_docs",
        **common,
        operations=[{"op": "create", "kind": "notes", "data": {"id": "n2", "path": "n2.md"}}],
    )
    moved = env.call(
        "write_docs", **common, operations=[_update("n1", n1_version, set={"path": "other.md"})]
    )
    # 検証
    assert no_body_file.is_error
    assert "InvalidArgumentError" in no_body_file.text
    assert "operations[0].set.@body" in no_body_file.text
    assert without_body.is_error
    assert "operations[0].data.@body" in without_body.text
    assert moved.is_error
    assert "operations[0].set.path" in moved.text
    assert doc_1.read_text(encoding="utf-8") == doc_1_before
    assert (worktree / "notes" / "index.yaml").read_text(encoding="utf-8") == NOTES
    assert (worktree / "notes" / "n1.md").read_text(encoding="utf-8") == NOTE_1


EXISTING_BODIES = {"notes/n6.md": "# n6\n", "notes/n7.md": "# n7\n", "notes/n8.md": "# n8\n"}


def test_normal_when_existing_body_file_adopted(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """`@body` を渡さず既にあるファイルを指す `create`・`update`・`replace` が、そのファイルを本文のファイルにする（正常系）。"""
    # 準備
    files = {**_absent_files(sample_file_set, sample_config_text), **EXISTING_BODIES}
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    common = {"cwd": str(source.folder), "worktree": str(worktree)}
    # 実行
    created = env.call(
        "write_docs",
        **common,
        operations=[{"op": "create", "kind": "notes", "data": {"id": "n6", "path": "n6.md"}}],
    )
    searched = env.call(
        "search_docs",
        **common,
        filter={"field": "id", "op": "eq", "values": ["n6"]},
        view="full",
        format="json",
    )
    updated = env.call(
        "write_docs",
        **common,
        operations=[_update("n3", value_hash({"id": "n3"}), set={"path": "n7.md"})],
    )
    replaced = env.call(
        "write_docs",
        **common,
        operations=[
            {
                "op": "replace",
                "id": "n5",
                "expected_version": value_hash({"id": "n5"}),
                "data": {"id": "n5", "path": "n8.md"},
            }
        ],
    )
    # 検証
    index = load_yaml((worktree / "notes" / "index.yaml").read_text(encoding="utf-8"))
    assert not created.is_error
    assert not updated.is_error
    assert not replaced.is_error
    assert index["items"] == [
        {"id": "n1", "path": "n1.md"},
        {"id": "n3", "path": "n7.md"},
        {"id": "n5", "path": "n8.md"},
        {"id": "n6", "path": "n6.md"},
    ]
    assert (worktree / "notes" / "n6.md").read_text(encoding="utf-8") == "# n6\n"
    assert (worktree / "notes" / "n7.md").read_text(encoding="utf-8") == "# n7\n"
    assert (worktree / "notes" / "n8.md").read_text(encoding="utf-8") == "# n8\n"
    assert "# n6" in searched.text
    assert "@@" not in created.data["results"][0]["diff"]
    assert "@@" not in updated.data["results"][0]["diff"]
    assert "@@" not in replaced.data["results"][0]["diff"]
    assert created.data["results"][0]["version"] == value_hash(
        [{"id": "n6", "path": "n6.md"}, "# n6\n"]
    )
    assert searched.data["items"][0]["values"]["version"] == created.data["results"][0]["version"]


DRAFTS_ROW = (
    "  - id: drafts\n"
    "    paths: [drafts/*.yaml]\n"
    "    exclude: [drafts/skip.yaml]\n"
    "    schema: schemas/sample.schema.yaml\n"
)
GENERATORS = "generators:\n  - id: generate\n    run: [python3, scripts/generate.py]\n"
GENERATE_SCRIPT = "print('generate')\n"
SKIPPED_DRAFT = "id: skip\nname: 除外\n"


def test_error_when_existing_body_file_not_adoptable(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """配信元のいずれかの文書のファイルか配信元の文書でないファイルを指す操作と、`@body` を渡して既にあるファイルを指す `create` を断り、直し方に取れる方法を示す（異常系）。"""
    # 準備
    files = {
        **_notes_files(sample_file_set, sample_config_text),
        # どの行も指さない生成の行と、`exclude[]` を持つ行 `drafts` を加えた配信元の設定
        "project-index.yaml": sample_config_text(NOTES_ROW + DRAFTS_ROW + GENERATORS),
        "notes/n6.md": "# n6\n",
        "scripts/generate.py": GENERATE_SCRIPT,
        "drafts/skip.yaml": SKIPPED_DRAFT,
    }
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    common = {"cwd": str(source.folder), "worktree": str(worktree)}
    doc_1_before = (worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8")
    config_before = (worktree / "project-index.yaml").read_text(encoding="utf-8")
    schema_before = (worktree / "schemas" / "notes.schema.yaml").read_text(encoding="utf-8")
    # 実行
    other_body = env.call(
        "write_docs",
        **common,
        operations=[{"op": "create", "kind": "notes", "data": {"id": "n10", "path": "n1.md"}}],
    )
    records_index = env.call(
        "write_docs",
        **common,
        operations=[{"op": "create", "kind": "notes", "data": {"id": "n11", "path": "index.yaml"}}],
    )
    document_file = env.call(
        "write_docs",
        **common,
        operations=[
            {"op": "create", "kind": "notes", "data": {"id": "n12", "path": "../docs/doc-1.yaml"}}
        ],
    )
    with_body = env.call(
        "write_docs",
        **common,
        operations=[
            {
                "op": "create",
                "kind": "notes",
                "data": {"id": "n13", "path": "n6.md", "@body": "本文\n"},
            }
        ],
    )
    config_file = env.call(
        "write_docs",
        **common,
        operations=[
            {
                "op": "create",
                "kind": "notes",
                "data": {"id": "n14", "path": "../project-index.yaml"},
            }
        ],
    )
    script_file = env.call(
        "write_docs",
        **common,
        operations=[
            {
                "op": "create",
                "kind": "notes",
                "data": {"id": "n15", "path": "../scripts/generate.py"},
            }
        ],
    )
    excluded_file = env.call(
        "write_docs",
        **common,
        operations=[
            {"op": "create", "kind": "notes", "data": {"id": "n16", "path": "../drafts/skip.yaml"}}
        ],
    )
    schema_file = env.call(
        "write_docs",
        **common,
        operations=[
            {
                "op": "create",
                "kind": "notes",
                "data": {"id": "n17", "path": "../schemas/notes.schema.yaml"},
            }
        ],
    )
    # 検証
    assert other_body.is_error
    assert "ValidationFailedError" in other_body.text
    assert "operations[0].path" in other_body.text
    assert "n1" in other_body.text
    assert "どれでもないパス" in other_body.text
    assert config_file.is_error
    assert "ValidationFailedError" in config_file.text
    assert "operations[0].path" in config_file.text
    assert "配信元の設定" in config_file.text
    assert "どれでもないパス" in config_file.text
    assert script_file.is_error
    assert "ValidationFailedError" in script_file.text
    assert "generators[generate]" in script_file.text
    assert excluded_file.is_error
    assert "ValidationFailedError" in excluded_file.text
    assert "drafts" in excluded_file.text
    assert "除外したファイル" in excluded_file.text
    assert schema_file.is_error
    assert "ValidationFailedError" in schema_file.text
    assert "documents[notes].schema" in schema_file.text
    assert records_index.is_error
    assert "ValidationFailedError" in records_index.text
    assert "notes" in records_index.text
    assert "管理用の YAML" in records_index.text
    assert document_file.is_error
    assert "ValidationFailedError" in document_file.text
    assert "doc-1" in document_file.text
    assert with_body.is_error
    assert "ValidationFailedError" in with_body.text
    assert "既にあります" in with_body.text
    assert "@body を除き" in with_body.text
    assert (worktree / "notes" / "index.yaml").read_text(encoding="utf-8") == NOTES
    assert (worktree / "notes" / "n1.md").read_text(encoding="utf-8") == NOTE_1
    assert (worktree / "notes" / "n6.md").read_text(encoding="utf-8") == "# n6\n"
    assert (worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8") == doc_1_before
    assert (worktree / "project-index.yaml").read_text(encoding="utf-8") == config_before
    assert (worktree / "scripts" / "generate.py").read_text(encoding="utf-8") == GENERATE_SCRIPT
    assert (worktree / "drafts" / "skip.yaml").read_text(encoding="utf-8") == SKIPPED_DRAFT
    assert (worktree / "schemas" / "notes.schema.yaml").read_text(encoding="utf-8") == schema_before


def test_normal_when_disk_storage(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """disk の配信元はクローン本体へ書き、created・updated を付ける（正常系）。"""
    # 準備
    config = sample_config_text('ids:\n  format: "{kind}-{slug}"\n', name="company")
    company = make_source(
        "company", sample_file_set(**{"project-index.yaml": config}), storage="disk"
    )
    env = make_server(company)
    cwd = str(company.folder)
    # 実行
    created = env.call(
        "write_docs",
        cwd=cwd,
        source="company",
        operations=[{"op": "create", "kind": "sample", "data": {"name": "メモ 1"}}],
    )
    target = company.folder / "docs" / f"{created.data['results'][0]['id']}.yaml"
    first = load_yaml(target.read_text(encoding="utf-8"))
    updated = env.call(
        "write_docs",
        cwd=cwd,
        source="company",
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
    assert not created.is_error
    assert "TargetIsCloneError" not in created.text
    assert created.data["results"][0]["status"] == "created"
    assert first["created"]
    assert first["updated"]
    assert updated.data["results"][0]["status"] == "updated"
    assert second["created"] == first["created"]
    assert str(second["updated"]) > str(first["updated"])


# 最上位の refs と functions[0].refs を持つ n1
NESTED_N1 = (
    "id: n1\nname: n1\nrefs:\n  - {to: n2, type: references}\n"
    "functions:\n  - name: f\n    refs:\n      - {to: n3, type: references}\n"
)


def test_error_when_recursive_metadata_key_written(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    nested_file_set: Callable[..., dict[str, str]],
) -> None:
    """**.{列名} の対応を持つ共通のキーは、書き込む場所を 1 つに決められないため断る（異常系）。"""
    # 準備
    files = nested_file_set(NESTED_N1)
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    target = worktree / "nested" / "n1.yaml"
    before = target.read_text(encoding="utf-8")
    link = [{"to": "n2", "type": "references"}]
    arguments = {"cwd": str(source.folder), "worktree": str(worktree)}
    # 実行
    first = env.call(
        "write_docs",
        operations=[_update("n1", _version(target), set={"related": link})],
        **arguments,
    )
    second = env.call(
        "write_docs", operations=[_update("n1", _version(target), unset=["related"])], **arguments
    )
    third = env.call(
        "write_docs",
        operations=[
            {"op": "create", "kind": "nested", "data": {"id": "n4", "name": "n4", "related": link}}
        ],
        **arguments,
    )
    unchanged = target.read_text(encoding="utf-8")
    fourth = env.call(
        "write_docs", operations=[_update("n1", _version(target), set={"refs": link})], **arguments
    )
    # 検証
    assert first.is_error
    assert "InvalidArgumentError" in first.text
    assert "operations[0].set.related" in first.text
    assert second.is_error
    assert "operations[0].unset" in second.text
    assert third.is_error
    assert "operations[0].data.related" in third.text
    assert not (worktree / "nested" / "n4.yaml").exists()
    assert unchanged == before
    assert all("functions[0].refs" in result.text for result in (first, second, third))
    assert not fourth.is_error
    after = load_yaml(target.read_text(encoding="utf-8"))
    assert after["refs"] == link
    assert after["functions"] == load_yaml(before)["functions"]


# 文書 1 が、関連・参照の型の値・Markdown のリンク・クラス図の click で文書 2 を指す
REFERRER_DOC = (
    "id: doc-1\n"
    "name: 文書 1\n"
    "ref: 'doc-2#items[a]'\n"
    "related:\n"
    "  - to: doc-2\n"
    "    type: references\n"
    "description: |-\n"
    "  [文書 2](id:doc-2) と [文書 20](id:doc-20)\n"
    '  click N href "id:doc-2#items[a]"\n'
)
# 目次の種類（`docs/index.yaml`）を持ち、sample から目次を除く配信元の設定
INDEX_CONFIG = (
    "name: sample\n"
    "default_ref: develop\n"
    "documents:\n"
    "  - id: sample\n"
    "    paths: [docs/*.yaml]\n"
    "    exclude: [index.yaml]\n"
    "    schema: schemas/sample.schema.yaml\n"
    "  - id: index\n"
    "    paths: [docs/index.yaml]\n"
    "    schema: schemas/index.schema.yaml\n"
    "    metadata:\n"
    "      id: page_id\n"
)
INDEX_SCHEMA = "type: object\n"
INDEX_DOC = "items:\n  - page: doc-2.yaml\n  - page: doc-1.yaml\n"
# ID の列の値を持たない（ID がパスの）本文のファイルを持つ行
PATH_ID_ROW = (
    "  - id: files\n"
    "    paths: [notes/files.yaml]\n"
    "    schema: schemas/files.schema.yaml\n"
    "    records: files\n"
    "    body_file: path\n"
)
PATH_ID_FILES = "files:\n  - path: n1.md\n    name: メモ 1\n  - path: n2.md\n    name: メモ 2\n"


# 文書 2 を `id:` のリンクと相対パスのリンクで指す本文のファイル（`notes/n1.md`）
REFERRER_BODY = (
    "[文書 2](id:doc-2#items[a])\n"
    "[文書 2](../docs/doc-2.yaml)\n"
    "[文書 20](id:doc-20) と、リンクでない文の doc-2\n"
)


def _rename(doc_id: str, version: str, **operation: Any) -> dict[str, Any]:
    """`rename` の操作を作る。"""
    return {"op": "rename", "id": doc_id, "expected_version": version, **operation}


def test_normal_when_rename(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
    sample_config_text: Callable[..., str],
) -> None:
    """`rename` で ID とファイル名を変え、同じ配信元の参照元を書き換える（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "docs/doc-1.yaml": REFERRER_DOC,
            "docs/doc-3.yaml": sample_doc_text("doc-3", "文書 3"),
            "project-index.yaml": sample_config_text(NOTES_ROW),
            "schemas/notes.schema.yaml": NOTES_SCHEMA,
            "notes/index.yaml": NOTES,
            "notes/n1.md": REFERRER_BODY,
        }
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    common = {"cwd": str(source.folder), "worktree": str(worktree)}
    operation = _rename("doc-2", _version(worktree / "docs" / "doc-2.yaml"), new_id="doc-9")
    doc_3 = (worktree / "docs" / "doc-3.yaml").read_text(encoding="utf-8")
    n1_version = value_hash([{"id": "n1", "path": "n1.md"}, REFERRER_BODY])
    # 実行
    tried = env.call("write_docs", **common, operations=[operation], dry_run=True)
    tried_exists = (worktree / "docs" / "doc-2.yaml").exists()
    tried_body = (worktree / "notes" / "n1.md").read_text(encoding="utf-8")
    renamed = env.call("write_docs", **common, operations=[operation])
    searched = env.call(
        "search_docs",
        **common,
        filter={"field": "id", "op": "eq", "values": ["doc-2", "doc-9"]},
        format="json",
    )
    # 検証
    results = {item["id"]: item for item in tried.data["results"]}
    first = results["doc-9"]
    referrer = results["doc-1"]
    note = results["n1"]
    written_note = next(item for item in renamed.data["results"] if item["id"] == "n1")
    text = (worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8")
    assert tried.data["applied"] is False
    assert tried_exists
    assert first["status"] == "renamed"
    assert first["id"] == "doc-9"
    assert first["renamed_from"] == "doc-2"
    assert first["path"] == "docs/doc-9.yaml"
    assert referrer["index"] == 0
    assert referrer["id"] == "doc-1"
    assert referrer["status"] == "updated"
    assert len(referrer["references"]) == 4
    assert not renamed.is_error
    assert not (worktree / "docs" / "doc-2.yaml").exists()
    assert load_yaml((worktree / "docs" / "doc-9.yaml").read_text(encoding="utf-8")) == {
        "id": "doc-9",
        "name": "文書 2",
        "description": "2 件目",
        "tags": ["a", "b"],
    }
    assert text == (
        "id: doc-1\n"
        "name: 文書 1\n"
        "ref: 'doc-9#items[a]'\n"
        "related:\n"
        "  - to: doc-9\n"
        "    type: references\n"
        "description: |-\n"
        "  [文書 2](id:doc-9) と [文書 20](id:doc-20)\n"
        '  click N href "id:doc-9#items[a]"\n'
    )
    assert (worktree / "docs" / "doc-3.yaml").read_text(encoding="utf-8") == doc_3
    assert [item["id"] for item in searched.data["items"]] == ["doc-9"]
    assert len(tried.data["results"]) == 3
    assert note["index"] == 0
    assert note["status"] == "updated"
    assert note["references"] == [
        {"path": "@body", "before": "id:doc-2", "after": "id:doc-9"},
        {"path": "@body", "before": "../docs/doc-2.yaml", "after": "../docs/doc-9.yaml"},
    ]
    assert "@@ notes/n1.md" in note["diff"]
    assert tried_body == REFERRER_BODY
    assert (worktree / "notes" / "n1.md").read_text(encoding="utf-8") == (
        "[文書 2](id:doc-9#items[a])\n"
        "[文書 2](../docs/doc-9.yaml)\n"
        "[文書 20](id:doc-20) と、リンクでない文の doc-2\n"
    )
    assert (worktree / "notes" / "index.yaml").read_text(encoding="utf-8") == NOTES
    assert written_note["version"] != n1_version


def test_normal_when_rename_path_only(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """`new_path` だけの `rename` でファイルを移し、パスで指す参照元を書き換える（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "project-index.yaml": INDEX_CONFIG,
            "schemas/index.schema.yaml": INDEX_SCHEMA,
            "docs/index.yaml": INDEX_DOC,
            "docs/doc-1.yaml": REFERRER_DOC,
        }
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    doc_1 = (worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8")
    operation = _rename(
        "doc-2", _version(worktree / "docs" / "doc-2.yaml"), new_path="docs/doc-2-old.yaml"
    )
    # 実行
    result = env.call(
        "write_docs", cwd=str(source.folder), worktree=str(worktree), operations=[operation]
    )
    # 検証
    assert not result.is_error
    assert result.data["results"][0]["id"] == "doc-2"
    assert result.data["results"][0]["path"] == "docs/doc-2-old.yaml"
    assert not (worktree / "docs" / "doc-2.yaml").exists()
    assert load_yaml((worktree / "docs" / "doc-2-old.yaml").read_text(encoding="utf-8"))["id"] == (
        "doc-2"
    )
    assert (worktree / "docs" / "index.yaml").read_text(encoding="utf-8") == (
        "items:\n  - page: doc-2-old.yaml\n  - page: doc-1.yaml\n"
    )
    assert (worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8") == doc_1


def test_normal_when_rename_body_file(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
    sample_doc_text: Callable[..., str],
) -> None:
    """`records`・`body_file` の行の文書を `new_path` で改名し、要素と本文のファイルを移す（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(PATH_ID_ROW),
            "schemas/files.schema.yaml": INDEX_SCHEMA,
            "notes/files.yaml": PATH_ID_FILES,
            "notes/n1.md": "# n1\n",
            "notes/n2.md": "# n2\n",
            "docs/doc-1.yaml": sample_doc_text(
                "doc-1", "文書 1", related=[{"to": "notes/n1.md", "type": "references"}]
            ),
        }
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    common = {"cwd": str(source.folder), "worktree": str(worktree)}
    version = value_hash([{"path": "n1.md", "name": "メモ 1"}, "# n1\n"])
    # 実行
    renamed = env.call(
        "write_docs",
        **common,
        operations=[_rename("notes/n1.md", version, new_path="notes/sub/n9.md")],
    )
    refused = env.call(
        "write_docs",
        **common,
        operations=[
            _rename(
                "notes/n2.md",
                value_hash([{"path": "n2.md", "name": "メモ 2"}, "# n2\n"]),
                new_id="n2",
            )
        ],
    )
    checked = env.call_admin("check_project", path=str(worktree), format="json")
    # 検証
    assert not renamed.is_error
    assert renamed.data["results"][0]["id"] == "notes/sub/n9.md"
    assert load_yaml((worktree / "notes" / "files.yaml").read_text(encoding="utf-8")) == {
        "files": [{"path": "sub/n9.md", "name": "メモ 1"}, {"path": "n2.md", "name": "メモ 2"}]
    }
    assert (worktree / "notes" / "sub" / "n9.md").read_text(encoding="utf-8") == "# n1\n"
    assert not (worktree / "notes" / "n1.md").exists()
    assert load_yaml((worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8"))["related"] == [
        {"to": "notes/sub/n9.md", "type": "references"}
    ]
    assert "notes/n1.md" not in checked.text
    assert "notes/sub/n9.md" not in checked.text
    assert refused.is_error
    assert "InvalidArgumentError" in refused.text
    assert (worktree / "notes" / "n2.md").exists()


def test_error_when_rename_id_exists(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
) -> None:
    """`new_id` が既にある文書の ID と重なる `rename` を断る（異常系）。"""
    # 準備
    source, env, worktree = _setup(make_source, make_server, add_worktree)
    doc_1 = (worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8")
    doc_2 = (worktree / "docs" / "doc-2.yaml").read_text(encoding="utf-8")
    operation = _rename("doc-2", _version(worktree / "docs" / "doc-2.yaml"), new_id="doc-1")
    # 実行
    result = env.call(
        "write_docs", cwd=str(source.folder), worktree=str(worktree), operations=[operation]
    )
    # 検証
    assert result.is_error
    assert "ValidationFailedError" in result.text
    assert "operations[0].new_id" in result.text
    assert "doc-1 は既にあります" in result.text
    assert (worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8") == doc_1
    assert (worktree / "docs" / "doc-2.yaml").read_text(encoding="utf-8") == doc_2


@pytest.mark.parametrize(
    ("new_path", "reason"),
    [
        pytest.param("other/doc-2.yaml", "paths に該当しない", id="outside_paths"),
        pytest.param("docs/doc-1.yaml", "既にあります", id="exists"),
    ],
)
def test_error_when_rename_path_invalid(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    new_path: str,
    reason: str,
) -> None:
    """配置先に該当しない `new_path` と既にあるファイルを指す `new_path` を断る（異常系）。"""
    # 準備
    source, env, worktree = _setup(make_source, make_server, add_worktree)
    doc_2 = (worktree / "docs" / "doc-2.yaml").read_text(encoding="utf-8")
    operation = _rename("doc-2", _version(worktree / "docs" / "doc-2.yaml"), new_path=new_path)
    # 実行
    result = env.call(
        "write_docs", cwd=str(source.folder), worktree=str(worktree), operations=[operation]
    )
    # 検証
    assert result.is_error
    assert "InvalidArgumentError" in result.text
    assert new_path in result.text
    assert reason in result.text
    assert (worktree / "docs" / "doc-2.yaml").read_text(encoding="utf-8") == doc_2
    assert not (worktree / "other").exists()


CHARS_CONFIG = (
    "name: sample\n"
    "default_ref: develop\n"
    "documents:\n"
    "  - id: asset\n"
    "    paths: [chars/*/*.yaml]\n"
    "    exclude: [chars/*/definition.yaml]\n"
    "    schema: schemas/note.schema.yaml\n"
    "  - id: definition\n"
    "    paths: [chars/*/definition.yaml]\n"
    "    schema: schemas/note.schema.yaml\n"
    "  - id: items\n"
    "    paths: [items/list.yaml]\n"
    "    schema: schemas/note.schema.yaml\n"
    "    records: items\n"
    "direct_commit:\n"
    "  branch: develop\n"
    "  kinds: [asset]\n"
)


def _create(kind: str, doc_id: str, new_path: str | None = None) -> dict[str, Any]:
    """`create` の操作を作る（`new_path` を省けば今までどおり配置先を決める）。"""
    operation: dict[str, Any] = {
        "op": "create",
        "kind": kind,
        "data": {"id": doc_id, "name": doc_id},
    }
    if new_path is not None:
        operation["new_path"] = new_path
    return operation


def test_normal_when_create_with_new_path(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """`create` の `new_path` で、フォルダの階層に glob を持つ種類の文書を指定したパスに作成する（正常系）。"""
    # 準備
    direct = make_direct_commit_source(config=CHARS_CONFIG, files={"chars/.keep": ""})
    env = make_server(direct.spec)

    def write(operation: dict[str, Any]) -> Any:
        return env.call(
            "write_docs", cwd=str(direct.folder), worktree=str(direct.x), operations=[operation]
        )

    # 実行
    first = write(_create("asset", "a1", "chars/c1/a1.yaml"))
    second = write(_create("definition", "c1-definition", "chars/c1/definition.yaml"))
    third = write(_create("asset", "a3"))
    fourth = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[_create("asset", "a2", "chars/c2/a2.yaml")],
        commit={"message": "docs: 表情を追加する"},
    )
    # 検証
    listed = env.call(
        "search_docs",
        cwd=str(direct.folder),
        worktree=str(direct.x),
        source="sample",
        filter={"field": "id", "op": "eq", "values": ["a1", "c1-definition"]},
        fields=["kind"],
        format="json",
    )
    kinds = {item["id"]: item["values"]["kind"] for item in listed.data["items"]}
    remote_after = run_git(direct.bare, "rev-parse", "develop").strip()
    changed = run_git(direct.bare, "show", "--name-only", "--format=%s", remote_after).split("\n")
    assert not first.is_error, first.text
    assert first.data["results"][0]["status"] == "created"
    assert first.data["results"][0]["id"] == "a1"
    assert not second.is_error, second.text
    assert second.data["results"][0]["status"] == "created"
    assert (direct.x / "chars/c1/a1.yaml").is_file()
    assert (direct.x / "chars/c1/definition.yaml").is_file()
    assert kinds["a1"] == "asset"
    assert kinds["c1-definition"] == "definition"
    assert third.is_error
    assert "asset の新しい文書の配置先を決められません" in third.text
    assert not fourth.is_error, fourth.text
    assert fourth.data["results"][0]["status"] == "created"
    assert fourth.data["commit"]["sha"] == remote_after
    assert changed[0] == "docs: 表情を追加する"
    assert "chars/c2/a2.yaml" in changed[1:]
    assert (direct.develop / "chars/c2/a2.yaml").is_file()


@pytest.mark.parametrize(
    ("kind", "new_path", "reason"),
    [
        pytest.param(
            "asset",
            "other/a2.yaml",
            "paths に該当しないか exclude に該当します",
            id="outside_paths",
        ),
        pytest.param(
            "asset",
            "chars/c1/definition.yaml",
            "paths に該当しないか exclude に該当します",
            id="excluded",
        ),
        pytest.param("asset", "chars/c1/a1.yaml", "は既にあります", id="exists"),
        pytest.param("asset", "../outside/a2.yaml", "配信元の外を指します", id="parent"),
        pytest.param("asset", "{tmp}/a2.yaml", "配信元の外を指します", id="absolute"),
        pytest.param(
            "items",
            "items/x.yaml",
            "records を持つため create の new_path を受けません",
            id="records",
        ),
    ],
)
def test_error_when_create_path_invalid(
    tmp_path: Path,
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    kind: str,
    new_path: str,
    reason: str,
) -> None:
    """配置先に該当しない・既にあるファイル・配信元の外を指す `create` の `new_path` と、`records` を持つ行の `new_path` を断る（異常系）。"""
    # 準備
    existing = "id: a1\nname: 既存\n"
    direct = make_direct_commit_source(config=CHARS_CONFIG, files={"chars/c1/a1.yaml": existing})
    env = make_server(direct.spec)
    before = sorted(
        str(path.relative_to(direct.x)) for path in direct.x.rglob("*") if ".git" not in path.parts
    )
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.folder),
        worktree=str(direct.x),
        operations=[_create(kind, "a9", new_path.format(tmp=tmp_path))],
    )
    # 検証
    after = sorted(
        str(path.relative_to(direct.x)) for path in direct.x.rglob("*") if ".git" not in path.parts
    )
    assert result.is_error
    assert "InvalidArgumentError" in result.text
    assert "operations[0].new_path" in result.text
    assert reason in result.text
    assert after == before
    assert (direct.x / "chars/c1/a1.yaml").read_text(encoding="utf-8") == existing
    assert not (direct.x.parent / "outside").exists()
    assert not (tmp_path / "a2.yaml").exists()


ANYWHERE_CONFIG = (
    "name: sample\n"
    "default_ref: develop\n"
    "documents:\n"
    "  - id: anywhere\n"
    "    paths: ['**/*.yaml']\n"
    "    exclude: [project-index.yaml, schemas/note.schema.yaml, schemas/rule.schema.yaml]\n"
    "    schema: schemas/note.schema.yaml\n"
)


@pytest.mark.parametrize(
    "new_path",
    [
        pytest.param("../outside/a1.yaml", id="parent"),
        pytest.param("anywhere/../../outside/a1.yaml", id="parent_after_normalize"),
        pytest.param("{tmp}/a1.yaml", id="absolute"),
    ],
)
def test_error_when_rename_path_outside_source(
    tmp_path_factory: pytest.TempPathFactory,
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    new_path: str,
) -> None:
    """`paths` が `**` で始まる種類でも、配信元の外を指す 1 ファイル 1 文書の `rename` の `new_path` を `paths` の照合より先に断る（異常系）。"""
    # 準備
    existing = "id: a1\nname: a1\n"
    direct = make_direct_commit_source(config=ANYWHERE_CONFIG, files={"anywhere/a1.yaml": existing})
    env = make_server(direct.spec)
    outside = tmp_path_factory.mktemp("outside")
    requested = new_path.format(tmp=outside)
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.folder),
        worktree=str(direct.x),
        operations=[_rename("a1", _version(direct.x / "anywhere/a1.yaml"), new_path=requested)],
    )
    # 検証
    assert result.is_error
    assert "InvalidArgumentError" in result.text
    assert "operations[0].new_path" in result.text
    assert f"new_path（{requested}）が配信元の外を指します" in result.text
    assert "配信元の直下からのパスを指定してください" in result.text
    assert (direct.x / "anywhere/a1.yaml").read_text(encoding="utf-8") == existing
    assert not (direct.x.parent / "outside").exists()
    assert not (outside / "a1.yaml").exists()


WORD_DOC_1 = (
    "id: doc-1\n"
    "name: 文書 1\n"
    "# コメントは残す\n"
    "description: '旧語'\n"
    "tags: [a]\n"
    "items:\n"
    "  - key: k1\n"
    "    label: 旧語と旧語\n"
    "notes:\n"
    "  旧語: 旧語\n"
)
WORD_DOC_2 = "id: doc-2\nname: 旧語\ntags: [a]\n"
WORD_DOC_3 = "id: doc-3\nname: 旧語\n"


def _replace_text(**operation: Any) -> dict[str, Any]:
    """タグ `a` の文書の `旧語` を置換する `replace_text` の操作を作る。"""
    return {
        "op": "replace_text",
        "filter": {"field": "tags", "op": "eq", "values": ["a"]},
        "old": "旧語",
        **operation,
    }


def _word_files(sample_file_set: Callable[..., dict[str, str]]) -> dict[str, str]:
    """タグ `a` の文書 2 件と持たない文書 1 件が `旧語` を持つ配信元のファイル一式を返す。"""
    return sample_file_set(
        **{
            "docs/doc-1.yaml": WORD_DOC_1,
            "docs/doc-2.yaml": WORD_DOC_2,
            "docs/doc-3.yaml": WORD_DOC_3,
        }
    )


# タグ `a` を持つ n1 と持たない n2 が、本文のファイルに `旧語` を持つ（要素の YAML は持たない）
WORD_NOTES = "items:\n  - id: n1\n    path: n1.md\n    tags: [a]\n  - id: n2\n    path: n2.md\n"
WORD_NOTE_1 = "# 旧語\n旧語と別の語\n"
WORD_NOTE_2 = "# 旧語\n"


def test_normal_when_replace_text(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """`replace_text` で `filter` に該当する文書の配下の文字列を置換し、文書ごとの件数を返す（正常系）。"""
    # 準備
    files = {
        **_word_files(sample_file_set),
        "project-index.yaml": sample_config_text(NOTES_ROW),
        "schemas/notes.schema.yaml": NOTES_SCHEMA,
        "notes/index.yaml": WORD_NOTES,
        "notes/n1.md": WORD_NOTE_1,
        "notes/n2.md": WORD_NOTE_2,
    }
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    common = {"cwd": str(source.folder), "worktree": str(worktree)}
    # 実行
    tried = env.call("write_docs", **common, operations=[_replace_text(new="新語")], dry_run=True)
    tried_text = (worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8")
    replaced = env.call("write_docs", **common, operations=[_replace_text(new="新語")])
    replaced_1 = (worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8")
    replaced_2 = (worktree / "docs" / "doc-2.yaml").read_text(encoding="utf-8")
    replaced_note_1 = (worktree / "notes" / "n1.md").read_text(encoding="utf-8")
    replaced_note_2 = (worktree / "notes" / "n2.md").read_text(encoding="utf-8")
    replaced_notes = (worktree / "notes" / "index.yaml").read_text(encoding="utf-8")
    # 置換の前の内容に戻してから、`fields` で項目を絞る
    (worktree / "docs" / "doc-1.yaml").write_text(WORD_DOC_1, encoding="utf-8")
    (worktree / "docs" / "doc-2.yaml").write_text(WORD_DOC_2, encoding="utf-8")
    (worktree / "notes" / "n1.md").write_text(WORD_NOTE_1, encoding="utf-8")
    narrowed = env.call(
        "write_docs", **common, operations=[_replace_text(new="新語", fields=["items"])]
    )
    narrowed_1 = (worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8")
    narrowed_2 = (worktree / "docs" / "doc-2.yaml").read_text(encoding="utf-8")
    narrowed_note_1 = (worktree / "notes" / "n1.md").read_text(encoding="utf-8")
    # 置換の前の内容に戻してから、`fields` で本文のファイルだけを置換する
    (worktree / "docs" / "doc-1.yaml").write_text(WORD_DOC_1, encoding="utf-8")
    body_only = env.call(
        "write_docs", **common, operations=[_replace_text(new="新語", fields=["@body"])]
    )
    # 検証
    assert tried.data["applied"] is False
    assert [(i["index"], i["id"], i["status"], i["count"]) for i in tried.data["results"]] == [
        (0, "doc-1", "updated", 4),
        (0, "doc-2", "updated", 1),
        (0, "n1", "updated", 2),
    ]
    assert all(item["diff"] for item in tried.data["results"])
    assert "@@ notes/n1.md" in tried.data["results"][2]["diff"]
    assert tried_text == WORD_DOC_1
    assert not replaced.is_error
    assert replaced_1 == (
        WORD_DOC_1.replace("'旧語'", "'新語'")
        .replace("旧語と旧語", "新語と新語")
        .replace("  旧語: 旧語\n", "  旧語: 新語\n")
    )
    assert replaced_2 == "id: doc-2\nname: 新語\ntags: [a]\n"
    assert (worktree / "docs" / "doc-3.yaml").read_text(encoding="utf-8") == WORD_DOC_3
    assert [(item["id"], item["count"]) for item in narrowed.data["results"]] == [("doc-1", 2)]
    assert narrowed_1 == WORD_DOC_1.replace("旧語と旧語", "新語と新語")
    assert narrowed_2 == WORD_DOC_2
    assert replaced_note_1 == "# 新語\n新語と別の語\n"
    assert replaced_note_2 == WORD_NOTE_2
    assert replaced_notes == WORD_NOTES
    assert narrowed_note_1 == WORD_NOTE_1
    assert [(item["id"], item["count"]) for item in body_only.data["results"]] == [("n1", 2)]
    assert (worktree / "notes" / "n1.md").read_text(encoding="utf-8") == "# 新語\n新語と別の語\n"
    assert (worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8") == WORD_DOC_1


def test_error_when_replace_text_validation_failed(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """置換した文書が 1 件でも検査に合格しなければ、どの文書も書き換えない（異常系）。"""
    # 準備
    one_line_name = SAMPLE_SCHEMA_ONE_LINE_NAME
    files = {**_word_files(sample_file_set), "schemas/sample.schema.yaml": one_line_name}
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    common = {"cwd": str(source.folder), "worktree": str(worktree)}
    doc_3 = _version(worktree / "docs" / "doc-3.yaml")
    update = _update("doc-3", doc_3, set={"description": "書き換えた"})
    # 実行
    failed = env.call("write_docs", **common, operations=[_replace_text(new="新\n語")])
    partial = env.call(
        "write_docs",
        **common,
        operations=[_replace_text(new="新\n語"), update],
        atomic=False,
    )
    # 検証
    assert failed.is_error
    assert "ValidationFailedError" in failed.text
    assert "doc-2#name" in failed.text
    assert (worktree / "docs" / "doc-1.yaml").read_text(encoding="utf-8") == WORD_DOC_1
    assert (worktree / "docs" / "doc-2.yaml").read_text(encoding="utf-8") == WORD_DOC_2
    assert [item["status"] for item in partial.data["results"]] == ["failed", "updated"]
    assert (worktree / "docs" / "doc-2.yaml").read_text(encoding="utf-8") == WORD_DOC_2
    assert "書き換えた" in (worktree / "docs" / "doc-3.yaml").read_text(encoding="utf-8")


# `name` に改行を許可しないスキーマ
SAMPLE_SCHEMA_ONE_LINE_NAME = (
    "type: object\n"
    "required: [id, name]\n"
    "properties:\n"
    "  id: {type: string}\n"
    "  name: {type: string, pattern: '^[^\\n]+$'}\n"
)


def test_error_when_builtin_source_written(
    make_builtin_clone: Callable[[], Path],
    make_server: Callable[..., Any],
) -> None:
    """scope.write を持たない組み込みの配信元への書き込みを断る（異常系）。"""
    # 準備
    clone = make_builtin_clone()
    env = make_server()
    target = clone / "docs" / "guide" / "files.yml"
    before = target.read_text(encoding="utf-8")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(clone),
        source="project-index",
        operations=[
            _update("docs/guide/配信元を登録する.md", "0000000", set={"name": "新しい名前"})
        ],
    )
    # 検証
    assert result.is_error
    assert "SourceNotWritableError" in result.text
    assert "project-index" in result.text
    assert target.read_text(encoding="utf-8") == before


NOTE_CREATE = {"op": "create", "kind": "note", "data": {"id": "n1", "name": "メモ 1"}}
NOTE_COMMIT = {"message": "docs: note を追加する"}


def _git_state(direct: DirectCommitSource, run_git: Callable[..., str]) -> tuple[str, str, str]:
    """リモートの develop・develop のワークツリーの HEAD・git status の組を返す。"""
    return (
        run_git(direct.bare, "rev-parse", "develop").strip(),
        run_git(direct.develop, "rev-parse", "HEAD").strip(),
        run_git(direct.develop, "status", "--porcelain").strip(),
    )


def test_normal_when_direct_commit(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """直コミットする（正常系）。"""
    # 準備
    direct = make_direct_commit_source()
    env = make_server(direct.spec)
    remote_before = run_git(direct.bare, "rev-parse", "develop").strip()
    x_head = run_git(direct.x, "rev-parse", "HEAD").strip()
    clone_status = run_git(direct.folder, "status", "--porcelain")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[NOTE_CREATE],
        commit=NOTE_COMMIT,
    )
    # 検証
    data = result.data
    remote_after = run_git(direct.bare, "rev-parse", "develop").strip()
    changed = run_git(direct.bare, "show", "--name-only", "--format=%s", remote_after).split("\n")
    assert not result.is_error, result.text
    assert data["applied"] is True
    assert data["results"][0]["status"] == "created"
    assert data["commit"]["branch"] == "develop"
    assert data["commit"]["retried"] is False
    assert data["commit"]["sha"] == remote_after
    assert run_git(direct.bare, "rev-parse", f"{remote_after}~1").strip() == remote_before
    assert changed[0] == "docs: note を追加する"
    assert sorted(line for line in changed[1:] if line) == ["generated/notes.txt", "notes/n1.yaml"]
    assert run_git(direct.develop, "rev-parse", "HEAD").strip() == remote_after
    assert run_git(direct.develop, "status", "--porcelain").strip() == ""
    assert run_git(direct.x, "rev-parse", "HEAD").strip() == x_head
    assert run_git(direct.folder, "status", "--porcelain") == clone_status


def test_normal_when_direct_commit_keeps_other_changes(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """直コミットで他の未コミットの変更を残す（正常系）。"""
    # 準備
    direct = make_direct_commit_source()
    env = make_server(direct.spec)
    (direct.develop / "memo.txt").write_text("書きかけ\n", encoding="utf-8")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[NOTE_CREATE],
        commit=NOTE_COMMIT,
    )
    # 検証
    sha = result.data["commit"]["sha"]
    changed = run_git(direct.bare, "show", "--name-only", "--format=", sha).split()
    assert not result.is_error, result.text
    assert "memo.txt" not in changed
    assert run_git(direct.develop, "status", "--porcelain").strip() == "M memo.txt"
    assert (direct.develop / "memo.txt").read_text(encoding="utf-8") == "書きかけ\n"


def test_normal_when_direct_commit_branch_overridden(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """直コミットのブランチを上書きする（正常系）。"""
    # 準備
    direct = make_direct_commit_source(
        config=direct_commit_config(branches=("data",)), extra_branches=("data",)
    )
    env = make_server(direct.spec)
    develop_before = run_git(direct.bare, "rev-parse", "develop").strip()
    data_before = run_git(direct.bare, "rev-parse", "data").strip()
    develop_head = run_git(direct.develop, "rev-parse", "HEAD").strip()
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[NOTE_CREATE],
        commit={**NOTE_COMMIT, "branch": "data"},
    )
    # 検証
    data_after = run_git(direct.bare, "rev-parse", "data").strip()
    assert not result.is_error, result.text
    assert result.data["commit"]["branch"] == "data"
    assert result.data["commit"]["sha"] == data_after
    assert run_git(direct.bare, "rev-parse", f"{data_after}~1").strip() == data_before
    assert "notes/n1.yaml" in run_git(direct.bare, "show", "--name-only", "--format=", data_after)
    assert run_git(direct.bare, "rev-parse", "develop").strip() == develop_before
    assert run_git(direct.develop, "rev-parse", "HEAD").strip() == develop_head


def test_normal_when_direct_commit_remote_ahead(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
    push_from_other_clone: Callable[..., str],
) -> None:
    """直コミットでリモートが先に進んでいる（正常系）。"""
    # 準備
    direct = make_direct_commit_source()
    env = make_server(direct.spec)
    ahead = push_from_other_clone(direct.bare, {"other.txt": "other\n"})
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[NOTE_CREATE],
        commit=NOTE_COMMIT,
    )
    # 検証
    sha = result.data["commit"]["sha"]
    assert not result.is_error, result.text
    assert run_git(direct.bare, "rev-parse", "develop").strip() == sha
    assert run_git(direct.bare, "rev-parse", f"{sha}~1").strip() == ahead
    assert result.data["commit"]["retried"] is False


def test_normal_when_direct_commit_push_rejected_once(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
    install_hook: Callable[..., None],
) -> None:
    """直コミットのプッシュが 1 回断られる（正常系）。"""
    # 準備
    direct = make_direct_commit_source()
    env = make_server(direct.spec)
    marker = direct.bare / "rejected-once"
    install_hook(
        direct.bare,
        "pre-receive",
        f'if [ ! -f "{marker}" ]; then touch "{marker}"; echo "try again" >&2; exit 1; fi\nexit 0',
    )
    remote_before = run_git(direct.bare, "rev-parse", "develop").strip()
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[NOTE_CREATE],
        commit=NOTE_COMMIT,
    )
    # 検証
    sha = result.data["commit"]["sha"]
    assert not result.is_error, result.text
    assert result.data["commit"]["retried"] is True
    assert run_git(direct.bare, "rev-parse", "develop").strip() == sha
    assert run_git(direct.bare, "rev-parse", f"{sha}~1").strip() == remote_before
    assert run_git(direct.develop, "rev-parse", "HEAD").strip() == sha


def test_normal_when_direct_commit_dry_run(
    tmp_path: Path,
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """直コミットを試しに書く（正常系）。"""
    # 準備
    direct = make_direct_commit_source()
    env = make_server(direct.spec)
    run_git(direct.folder, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    before = _git_state(direct, run_git)
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[NOTE_CREATE],
        commit=NOTE_COMMIT,
        dry_run=True,
    )
    # 検証
    assert not result.is_error, result.text
    assert result.data["applied"] is False
    assert result.data["results"][0]["diff"]
    assert "commit" not in result.data
    assert _git_state(direct, run_git) == before


@dataclass
class _Target:
    """直コミットを呼ぶ配信元と作業場所。"""

    env: Any
    source_id: str
    cwd: Path
    # 参照（ブランチ・タグ）を比べるリポジトリと、作業ツリーの状態を比べるフォルダ
    refs: list[Path]
    trees: list[Path]


def _source_without_direct_commit(
    make_direct: Callable[..., DirectCommitSource], make_server: Callable[..., Any], **_: Any
) -> _Target:
    """direct_commit の無い sample。"""
    direct = make_direct(config=direct_commit_config().split("direct_commit:")[0])
    return _Target(
        make_server(direct.spec), "sample", direct.local, [direct.bare], [direct.develop]
    )


def _source_with_missing_kind(
    make_direct: Callable[..., DirectCommitSource], make_server: Callable[..., Any], **_: Any
) -> _Target:
    """direct_commit.kinds に documents[] に無い meme を持つ sample。"""
    direct = make_direct(config=direct_commit_config(kinds=("note", "meme")))
    return _Target(
        make_server(direct.spec), "sample", direct.local, [direct.bare], [direct.develop]
    )


def _disk_source(
    make_direct: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    *,
    make_source: Callable[..., Any],
    tmp_path: Path,
) -> _Target:
    """direct_commit を持つ disk の配信元 company。"""
    local = tmp_path / "local"
    local.mkdir(exist_ok=True)
    spec = make_source(
        "company",
        {
            "project-index.yaml": direct_commit_config().replace("name: sample", "name: company"),
            "schemas/note.schema.yaml": NOTE_SCHEMA,
            "schemas/rule.schema.yaml": DIRECT_RULE_SCHEMA,
            "scripts/list.py": NOTE_LIST_SCRIPT,
        },
        storage="disk",
    )
    spec.direct_commit_scope = [local]
    return _Target(make_server(spec), "company", local, [spec.folder], [spec.folder])


def _tree_state(target: _Target, run_git: Callable[..., str]) -> list[str]:
    """リポジトリの参照と、作業ツリーの状態を返す。"""
    return [run_git(path, "for-each-ref") for path in target.refs] + [
        run_git(path, "status", "--porcelain") for path in target.trees
    ]


@pytest.mark.parametrize(
    ("build", "reason"),
    [
        pytest.param(_source_without_direct_commit, "直コミットの設定が無い", id="absent"),
        pytest.param(_source_with_missing_kind, "meme", id="missing-kind"),
        pytest.param(_disk_source, "disk の配信元である", id="disk"),
    ],
)
def test_error_when_direct_commit_not_configured(
    build: Callable[..., _Target],
    reason: str,
    tmp_path: Path,
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """直コミットの設定が無い（異常系）。"""
    # 準備
    target = build(
        make_direct_commit_source, make_server, make_source=make_source, tmp_path=tmp_path
    )
    before = _tree_state(target, run_git)
    # 実行
    result = target.env.call(
        "write_docs",
        cwd=str(target.cwd),
        source=target.source_id,
        operations=[NOTE_CREATE],
        commit=NOTE_COMMIT,
    )
    # 検証
    assert result.is_error
    assert "DirectCommitNotConfiguredError" in result.text
    assert target.source_id in result.text
    assert reason in result.text
    assert _tree_state(target, run_git) == before


def test_error_when_direct_commit_kind_not_allowed(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """直コミットを許可していない種類（異常系）。"""
    # 準備
    direct = make_direct_commit_source()
    env = make_server(direct.spec)
    before = _git_state(direct, run_git)
    operation = {"op": "create", "kind": "rule", "data": {"id": "r9", "name": "規約 9"}}
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[operation],
        commit=NOTE_COMMIT,
    )
    # 検証
    assert result.is_error
    assert "ValidationFailedError" in result.text
    assert "rule は直コミットを許可していない種類です" in result.text
    assert "index: 0" in result.text
    assert _git_state(direct, run_git) == before


F1_VERSION = value_hash([{"id": "f1", "name": "案内", "path": "f1.md"}, F1_BODY])


def test_normal_when_direct_commit_metadata_only(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """本文の直コミットを断る種類のメタデータだけを直コミットする（正常系）。"""
    # 準備
    direct = make_direct_commit_source(config=metadata_only_config(), files=METADATA_ONLY_FILES)
    env = make_server(direct.spec)
    operation = {
        "op": "update",
        "id": "f1",
        "expected_version": F1_VERSION,
        "set": {"description": "変えた案内", "tags": ["topic:a"]},
    }
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[operation],
        commit={"message": "docs: files を更新する"},
    )
    # 検証
    remote_after = run_git(direct.bare, "rev-parse", "develop").strip()
    changed = run_git(direct.bare, "show", "--name-only", "--format=", remote_after).split()
    assert not result.is_error, result.text
    assert result.data["applied"] is True
    assert result.data["results"][0]["status"] == "updated"
    assert result.data["commit"]["sha"] == remote_after
    assert changed == ["files/index.yaml"]
    assert (direct.develop / "files" / "f1.md").read_text(encoding="utf-8") == F1_BODY


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(
            {"op": "update", "id": "f1", "expected_version": F1_VERSION, "set": {"@body": "x\n"}},
            id="set-body",
        ),
        pytest.param(
            {
                "op": "update",
                "id": "f1",
                "expected_version": F1_VERSION,
                "text_edits": [{"field": "@body", "old": "メモ 1", "new": "メモ X"}],
            },
            id="text-edits-body",
        ),
        pytest.param(
            {
                "op": "rename",
                "id": "f1",
                "expected_version": F1_VERSION,
                "new_path": "files/f2.md",
            },
            id="rename-new-path",
        ),
        pytest.param(
            {
                "op": "rename",
                "id": "n1",
                "expected_version": content_hash("id: n1\nname: メモ 1\n"),
                "new_id": "n9",
            },
            id="rename-referrer",
        ),
        pytest.param(
            {
                "op": "replace_text",
                "filter": {"field": "id", "op": "eq", "values": ["f1"]},
                "old": "メモ 1",
                "new": "メモ X",
            },
            id="replace-text",
        ),
    ],
)
def test_error_when_direct_commit_body_not_allowed(
    operation: dict[str, Any],
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """本文の直コミットを断る種類の本文が変わる（異常系）。"""
    # 準備
    direct = make_direct_commit_source(config=metadata_only_config(), files=METADATA_ONLY_FILES)
    env = make_server(direct.spec)
    before = _git_state(direct, run_git)
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[operation],
        commit={"message": "docs: files を更新する"},
    )
    # 検証
    assert result.is_error
    assert "ValidationFailedError" in result.text
    assert "種類 files は本文の直コミットを断っている" in result.text
    assert "index: 0" in result.text
    assert "doc: f1" in result.text
    assert _git_state(direct, run_git) == before
    assert (direct.develop / "files" / "f1.md").read_text(encoding="utf-8") == F1_BODY
    assert (direct.develop / "files" / "index.yaml").read_text(encoding="utf-8") == FILES_INDEX


def test_error_when_direct_commit_rewrites_other_kind(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """直コミットで許可していない種類の文書が書き換わる（異常系）。"""
    # 準備
    direct = make_direct_commit_source(
        files={
            "notes/n1.yaml": "id: n1\nname: メモ 1\n",
            "rules/r1.yaml": "id: r1\nname: 規約 1\nrelated:\n  - to: n1\n    type: references\n",
        }
    )
    env = make_server(direct.spec)
    before = _git_state(direct, run_git)
    version = _version(direct.develop / "notes" / "n1.yaml")
    operation = {"op": "rename", "id": "n1", "expected_version": version, "new_id": "n2"}
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[operation],
        commit=NOTE_COMMIT,
    )
    # 検証
    assert result.is_error
    assert "rule は直コミットを許可していない種類です" in result.text
    assert "r1" in result.text
    assert _git_state(direct, run_git) == before


@pytest.mark.parametrize(
    ("parts", "kind"),
    [
        pytest.param(("gh", "p_", "A1b2C3d4" * 4, "E5f6"), "github-token", id="github-token"),
        pytest.param(("連絡先 user", "@", "example.com"), "email-address", id="email-address"),
    ],
)
def test_error_when_direct_commit_contains_secret(
    parts: tuple[str, ...],
    kind: str,
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """直コミットで秘密の値を含む（異常系）。"""
    # 準備
    direct = make_direct_commit_source()
    env = make_server(direct.spec)
    before = _git_state(direct, run_git)
    value = "".join(parts)
    operation = {
        "op": "create",
        "kind": "note",
        "data": {"id": "n1", "name": "メモ 1", "description": value},
    }
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[operation],
        commit=NOTE_COMMIT,
    )
    # 検証
    assert result.is_error
    assert "description" in result.text
    assert f"秘密の値（{kind}）を含む" in result.text
    assert value not in result.text
    assert value not in str(result.structured)
    assert _git_state(direct, run_git) == before


def _elsewhere(direct: DirectCommitSource, tmp_path: Path) -> Path:
    """手元の作業場所でない空のフォルダ。"""
    path = tmp_path / "elsewhere"
    path.mkdir(exist_ok=True)
    return path


def _clone_folder(direct: DirectCommitSource, _tmp_path: Path) -> Path:
    """sample のフォルダ（scope.write に該当する）。"""
    return direct.folder


def _local_folder(direct: DirectCommitSource, _tmp_path: Path) -> Path:
    """手元の作業場所。"""
    return direct.local


@pytest.mark.parametrize(
    ("cwd_of", "kind_globs"),
    [
        pytest.param(_elsewhere, None, id="other-folder"),
        pytest.param(_clone_folder, None, id="scope-write"),
        pytest.param(_local_folder, {"note": [Path("/another")]}, id="kind-glob"),
    ],
)
def test_error_when_direct_commit_not_permitted(
    cwd_of: Callable[[DirectCommitSource, Path], Path],
    kind_globs: dict[str, list[Path]] | None,
    tmp_path: Path,
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """直コミットを呼べる作業場所に該当しない（異常系）。"""
    # 準備
    direct = make_direct_commit_source(direct_commit_kinds=kind_globs)
    env = make_server(direct.spec)
    before = _git_state(direct, run_git)
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(cwd_of(direct, tmp_path)),
        source="sample",
        operations=[NOTE_CREATE],
        commit=NOTE_COMMIT,
    )
    # 検証
    assert result.is_error
    assert "DirectCommitNotPermittedError" in result.text
    assert "sample の直コミットはできません" in result.text
    assert "note" in result.text
    assert _git_state(direct, run_git) == before


def test_error_when_branch_not_allowed(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """上書きできないブランチ（異常系）。"""
    # 準備
    direct = make_direct_commit_source(
        config=direct_commit_config(branches=("data",)), extra_branches=("data",)
    )
    env = make_server(direct.spec)
    refs = run_git(direct.bare, "for-each-ref")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[NOTE_CREATE],
        commit={**NOTE_COMMIT, "branch": "master"},
    )
    # 検証
    assert result.is_error
    assert "BranchNotAllowedError" in result.text
    assert "master" in result.text
    assert "develop, data" in result.text
    assert run_git(direct.bare, "for-each-ref") == refs
    assert run_git(direct.develop, "status", "--porcelain").strip() == ""


def test_error_when_commit_worktree_not_found(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """コミットするブランチのワークツリーが無い（異常系）。"""
    # 準備
    direct = make_direct_commit_source(config=direct_commit_config(branch="main"))
    env = make_server(direct.spec)
    before = _git_state(direct, run_git)
    clone_status = run_git(direct.folder, "status", "--porcelain")
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[NOTE_CREATE],
        commit=NOTE_COMMIT,
    )
    # 検証
    assert result.is_error
    assert "CommitWorktreeNotFoundError" in result.text
    assert "main を指すワークツリーがありません" in result.text
    assert _git_state(direct, run_git) == before
    assert run_git(direct.folder, "status", "--porcelain") == clone_status


def test_error_when_unpushed_commits(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
    commit_all: Callable[..., str],
) -> None:
    """直コミットで未プッシュのコミットがある（異常系）。"""
    # 準備
    direct = make_direct_commit_source()
    env = make_server(direct.spec)
    remote = run_git(direct.bare, "rev-parse", "develop").strip()
    local = commit_all(direct.develop, {"memo.txt": "未プッシュ\n"})
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[NOTE_CREATE],
        commit=NOTE_COMMIT,
    )
    # 検証
    assert result.is_error
    assert "UnpushedCommitsError" in result.text
    assert "先行 1" in result.text
    assert run_git(direct.bare, "rev-parse", "develop").strip() == remote
    assert run_git(direct.develop, "rev-parse", "HEAD").strip() == local
    assert not (direct.develop / "notes" / "n1.yaml").exists()


def test_error_when_uncommitted_changes(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """直コミットで書き込むファイルに未コミットの変更がある（異常系）。"""
    # 準備
    direct = make_direct_commit_source(files={"notes/n1.yaml": "id: n1\nname: メモ 1\n"})
    env = make_server(direct.spec)
    remote = run_git(direct.bare, "rev-parse", "develop").strip()
    note = direct.develop / "notes" / "n1.yaml"
    note.write_text("id: n1\nname: 書きかけ\n", encoding="utf-8")
    operation = _update("n1", _version(note), set={"name": "直コミット"})
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[operation],
        commit=NOTE_COMMIT,
    )
    # 検証
    assert result.is_error
    assert "UncommittedChangesError" in result.text
    assert "notes/n1.yaml" in result.text
    assert run_git(direct.bare, "rev-parse", "develop").strip() == remote
    assert note.read_text(encoding="utf-8") == "id: n1\nname: 書きかけ\n"


def test_error_when_fetch_failed(
    tmp_path: Path,
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """リモートから取得できない（異常系）。"""
    # 準備
    direct = make_direct_commit_source()
    env = make_server(direct.spec)
    run_git(direct.folder, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    head = run_git(direct.develop, "rev-parse", "HEAD").strip()
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[NOTE_CREATE],
        commit=NOTE_COMMIT,
    )
    # 検証
    assert result.is_error
    assert "FetchFailedError" in result.text
    assert "missing.git" in result.text
    assert run_git(direct.develop, "rev-parse", "HEAD").strip() == head
    assert not (direct.develop / "notes" / "n1.yaml").exists()


def test_error_when_push_rejected(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
    install_hook: Callable[..., None],
) -> None:
    """プッシュが 2 回断られる（異常系）。"""
    # 準備
    direct = make_direct_commit_source()
    env = make_server(direct.spec)
    install_hook(direct.bare, "pre-receive", "echo 'denied by policy' >&2\nexit 1")
    before = _git_state(direct, run_git)
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[NOTE_CREATE],
        commit=NOTE_COMMIT,
    )
    # 検証
    assert result.is_error
    assert "PushRejectedError" in result.text
    assert "denied by policy" in result.text
    assert _git_state(direct, run_git) == before
    assert not (direct.develop / "generated" / "notes.txt").exists()


def test_error_when_push_failed(
    tmp_path: Path,
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """プッシュで通信に失敗する（異常系）。"""
    # 準備
    direct = make_direct_commit_source()
    env = make_server(direct.spec)
    run_git(direct.folder, "remote", "set-url", "--push", "origin", str(tmp_path / "missing.git"))
    before = _git_state(direct, run_git)
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[NOTE_CREATE],
        commit=NOTE_COMMIT,
    )
    # 検証
    assert result.is_error
    assert "PushFailedError" in result.text
    assert "missing.git" in result.text
    assert _git_state(direct, run_git) == before
    assert not (direct.develop / "notes" / "n1.yaml").exists()


def _not_atomic(_direct: DirectCommitSource) -> dict[str, Any]:
    """atomic: false の引数。"""
    return {"atomic": False}


def _develop_worktree(direct: DirectCommitSource) -> dict[str, Any]:
    """develop のワークツリーを指す worktree の引数。"""
    return {"worktree": str(direct.develop)}


@pytest.mark.parametrize(
    ("extra", "rule"),
    [
        pytest.param(_not_atomic, "atomic: true の書き込みだけで使用できます", id="not-atomic"),
        pytest.param(_develop_worktree, "commit と worktree は同時に指定できません", id="worktree"),
    ],
)
def test_error_when_direct_commit_invalid_arguments(
    extra: Callable[[DirectCommitSource], dict[str, Any]],
    rule: str,
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """直コミットの引数の組み合わせの誤り（異常系）。"""
    # 準備
    direct = make_direct_commit_source()
    env = make_server(direct.spec)
    before = _git_state(direct, run_git)
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[NOTE_CREATE],
        commit=NOTE_COMMIT,
        **extra(direct),
    )
    # 検証
    assert result.is_error
    assert "InvalidArgumentError" in result.text
    assert rule in result.text
    assert _git_state(direct, run_git) == before


def test_error_when_direct_commit_generator_failed(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """直コミットで生成が失敗する（異常系）。"""
    # 準備
    direct = make_direct_commit_source(list_script=FAILING_SCRIPT)
    env = make_server(direct.spec)
    before = _git_state(direct, run_git)
    # 実行
    result = env.call(
        "write_docs",
        cwd=str(direct.local),
        source="sample",
        operations=[NOTE_CREATE],
        commit=NOTE_COMMIT,
    )
    # 検証
    assert result.is_error
    assert "DirectCommitGeneratorError" in result.text
    assert "scripts/list.py" in result.text
    assert _git_state(direct, run_git) == before


SKIPPED_SCHEMA = (
    "type: object\n"
    "title: サンプル\n"
    "properties:\n"
    "  id: {type: string}\n"
    "  name: {type: string}\n"
    "  notes:\n"
    "    type: object\n"
    "    additionalProperties: {type: string}\n"
    "  labels:\n"
    "    type: array\n"
    "    items: {type: string}\n"
)
SKIPPED_DOC = 'id: doc-1\nname: 文書 1\nnotes:\n  "mcp/server.py の補足": 補足\nlabels: [a]\n'


def test_normal_when_operation_skipped(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """何もしなかった unset・remove_from を results[].skipped に返却し、. を含むキーを # の項目のパスで削除する（正常系）。"""
    # 準備
    files = sample_file_set(
        **{"schemas/sample.schema.yaml": SKIPPED_SCHEMA, "docs/doc-1.yaml": SKIPPED_DOC}
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    path = worktree / "docs" / "doc-1.yaml"
    arguments = {"cwd": str(source.folder), "worktree": str(worktree)}

    def _call(**operation: Any) -> Any:
        return env.call(
            "write_docs", operations=[_update("doc-1", _version(path), **operation)], **arguments
        )

    # 実行
    first = _call(
        unset=["notes.mcp/server.py の補足", "notes.nonexistent"],
        remove_from={"labels": ["a", "z"], "missing": ["x"]},
    )
    after_first = load_yaml(path.read_text(encoding="utf-8"))
    second = _call(unset=["#notes[mcp/server.py の補足]"])
    after_second = load_yaml(path.read_text(encoding="utf-8"))
    # 検証
    assert [item["status"] for item in first.data["results"]] == ["updated"]
    assert after_first["labels"] == []
    assert after_first["notes"] == {"mcp/server.py の補足": "補足"}
    assert first.data["results"][0]["skipped"] == [
        {"path": "unset.notes.mcp/server.py の補足", "reason": "項目がありません"},
        {"path": "unset.notes.nonexistent", "reason": "項目がありません"},
        {"path": "remove_from.labels", "reason": "z の要素がありません"},
        {"path": "remove_from.missing", "reason": "項目がありません"},
    ]
    assert [item["status"] for item in second.data["results"]] == ["updated"]
    assert "notes" not in after_second or "mcp/server.py の補足" not in after_second["notes"]
    assert "skipped" not in second.data["results"][0]


def test_error_when_sqlite_kind_written(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
) -> None:
    """SQLite の表の行の種類への操作を含む呼び出しを、そのほかの操作も書き込まずに断る（異常系）。"""
    from tests.integration.server.conftest import sqlite_files, write_notes_db

    # 準備
    source, env, worktree = _setup(make_source, make_server, add_worktree, sqlite_files())
    db = write_notes_db(source.folder)
    db_before = db.read_bytes()
    first = worktree / "docs" / "doc-1.yaml"
    first_before = first.read_text(encoding="utf-8")
    operations = [
        _update("doc-1", _version(first), set={"name": "新しい名前"}),
        _update("n1", "000000", set={"title": "書き換え"}),
        {"op": "create", "kind": "notes_db", "data": {"id": "n9", "title": "追加"}},
    ]
    cwd = str(source.folder)
    # 実行
    atomic = env.call("write_docs", cwd=cwd, worktree=str(worktree), operations=operations)
    first_after_atomic = first.read_text(encoding="utf-8")
    not_atomic = env.call(
        "write_docs", cwd=cwd, worktree=str(worktree), operations=operations, atomic=False
    )
    replaced = env.call(
        "write_docs",
        cwd=cwd,
        worktree=str(worktree),
        operations=[
            {
                "op": "replace_text",
                "filter": {"field": "id", "op": "eq", "values": ["doc-2", "n1"]},
                "old": "1",
                "new": "一",
            }
        ],
    )
    # 検証
    assert atomic.is_error is True
    assert atomic.text.startswith("ReadOnlyKindError")
    assert "operations[1]" in atomic.text
    assert "operations[2]" in atomic.text
    assert "notes_db" in atomic.text
    assert first_after_atomic == first_before
    results = not_atomic.data["results"]
    assert not_atomic.data["applied"] is True
    assert [item["status"] for item in results] == ["updated", "failed", "failed"]
    assert "notes_db" in results[1]["errors"][0]["rule"]
    assert "notes_db" in results[2]["errors"][0]["rule"]
    assert load_yaml(first.read_text(encoding="utf-8"))["name"] == "新しい名前"
    assert "n1" not in [item.get("id") for item in replaced.data.get("results", [])]
    assert db.read_bytes() == db_before


def _slow_generator_files(
    sample_file_set: Callable[..., dict[str, str]], wait_sec: int
) -> dict[str, str]:
    """書き込んだ後に `wait_sec` 秒待つ生成のスクリプト `slow` を持つ配信元のファイル一式。"""
    config = (
        "name: sample\n"
        "default_ref: develop\n"
        "documents:\n"
        "  - id: sample\n"
        "    paths: [docs/*.yaml]\n"
        "    schema: schemas/sample.schema.yaml\n"
        "    after_write: [slow]\n"
        "generators:\n"
        "  - id: slow\n"
        "    run: [python3, scripts/slow.py]\n"
    )
    script = f"import time\ntime.sleep({wait_sec})\n"
    return sample_file_set(**{"project-index.yaml": config, "scripts/slow.py": script})


def _timed_call(env: Any, name: str, **arguments: Any) -> tuple[Any, float]:
    """ツールを呼び、結果と送信してから返却されるまでの秒数を返す。"""
    started = time.monotonic()
    result = env.call(name, **arguments)
    return result, time.monotonic() - started


def test_error_when_source_lock_wait_exceeds_deadline(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """同じ配信元の先の書き込みが排他を握ったままで、後から来た書き込みの期限を過ぎたら、後から来た書き込みは時間切れを返却する（異常系）。"""
    # 準備
    source = make_source("sample", _slow_generator_files(sample_file_set, 4))
    worktree = add_worktree(source.folder, "x")
    env = make_server(source, settings_extra="write_deadline_sec: 2\n")
    doc_1 = worktree / "docs" / "doc-1.yaml"
    doc_2 = worktree / "docs" / "doc-2.yaml"
    doc_2_before = doc_2.read_text(encoding="utf-8")
    common = {"cwd": str(source.folder), "worktree": str(worktree)}
    # 実行
    with ThreadPoolExecutor(max_workers=2) as pool:
        call_a = pool.submit(
            _timed_call,
            env,
            "write_docs",
            operations=[_update("doc-1", _version(doc_1), set={"name": "A の名前"})],
            **common,
        )
        time.sleep(0.5)
        call_b = pool.submit(
            _timed_call,
            env,
            "write_docs",
            operations=[_update("doc-2", _version(doc_2), set={"name": "B の名前"})],
            **common,
        )
        result_b, elapsed_b = call_b.result(timeout=30)
        result_a, _elapsed_a = call_a.result(timeout=30)
    # 検証
    assert result_b.is_error is True
    assert result_b.text.startswith("WriteDeadlineExceededError: 書き込みの期限")
    assert "ファイルを書き換えずに止めました" in result_b.text
    assert elapsed_b < 3
    assert not result_a.is_error
    assert result_a.data["applied"] is True
    assert "A の名前" in doc_1.read_text(encoding="utf-8")
    assert doc_2.read_text(encoding="utf-8") == doc_2_before


def test_error_when_source_lock_waiters_exceed_execution_slots(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """同じ配信元の排他を待つ書き込みが実行スロットの本数を超えても、ほかの配信元への書き込みと検索は待たずに返却する（異常系）。"""
    # 準備
    source = make_source("sample", _slow_generator_files(sample_file_set, 4))
    other = make_source(
        "sample2", sample_file_set(**{"project-index.yaml": sample_config_text(name="sample2")})
    )
    worktree = add_worktree(source.folder, "x")
    other_worktree = add_worktree(other.folder, "x")
    env = make_server(source, other, settings_extra="write_deadline_sec: 2\n")
    doc_1 = worktree / "docs" / "doc-1.yaml"
    doc_2 = worktree / "docs" / "doc-2.yaml"
    doc_2_before = doc_2.read_text(encoding="utf-8")
    other_doc = other_worktree / "docs" / "doc-1.yaml"
    sample = {"cwd": str(source.folder), "worktree": str(worktree)}
    sample2 = {"cwd": str(other.folder), "worktree": str(other_worktree)}
    waiters = DOCS_WORKERS + 1
    # 実行
    with ThreadPoolExecutor(max_workers=waiters + 3) as pool:
        call_a = pool.submit(
            _timed_call,
            env,
            "write_docs",
            operations=[_update("doc-1", _version(doc_1), set={"name": "A の名前"})],
            **sample,
        )
        time.sleep(0.5)
        calls_w = [
            pool.submit(
                _timed_call,
                env,
                "write_docs",
                operations=[_update("doc-2", _version(doc_2), set={"name": "W の名前"})],
                **sample,
            )
            for _ in range(waiters)
        ]
        time.sleep(0.2)
        call_c = pool.submit(
            _timed_call,
            env,
            "write_docs",
            operations=[_update("doc-1", _version(other_doc), set={"name": "C の名前"})],
            **sample2,
        )
        call_d = pool.submit(
            _timed_call,
            env,
            "search_docs",
            filter={"field": "id", "op": "eq", "values": ["doc-1"]},
            format="json",
            **sample2,
        )
        result_c, elapsed_c = call_c.result(timeout=30)
        result_d, elapsed_d = call_d.result(timeout=30)
        results_w = [call.result(timeout=30) for call in calls_w]
        call_a.result(timeout=30)
    # 検証
    assert not result_c.is_error
    assert result_c.data["applied"] is True
    assert elapsed_c < 1
    assert not result_d.is_error
    assert elapsed_d < 1
    assert all(result.is_error for result, _ in results_w)
    assert all(
        result.text.startswith("WriteDeadlineExceededError: 書き込みの期限")
        for result, _ in results_w
    )
    assert all(elapsed < 3 for _, elapsed in results_w)
    assert doc_2.read_text(encoding="utf-8") == doc_2_before

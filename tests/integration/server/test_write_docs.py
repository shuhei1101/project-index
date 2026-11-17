from __future__ import annotations

import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from project_index.shared.hashing import content_hash, value_hash
from project_index.shared.yaml_io import load_yaml as load_yaml_value

if TYPE_CHECKING:
    from collections.abc import Callable


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

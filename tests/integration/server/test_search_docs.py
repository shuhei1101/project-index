from __future__ import annotations

import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.integration.server.conftest import DirectCommitSource, SourceSpec

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

FILES_SCHEMA = Path(__file__).parents[3] / "templates" / "files.schema.yaml"
BROKEN_CONFIG = "name: broken\ndocuments:\n  - id: sample\n    schema: schemas/sample.schema.yaml\n"
BY_ID = {"field": "id", "op": "eq", "values": ["doc-2", "doc-1"]}
DOC_1 = {"field": "id", "op": "eq", "values": ["doc-1"]}
NOTES_ROWS = (
    "  - id: notes\n"
    "    paths: [notes/**/files.yaml]\n"
    "    schema: schemas/sample.schema.yaml\n"
    "    records: files\n"
    "    body_file: path\n"
)
SEARCH_WORD = {"field": "body", "op": "contains", "values": ["検索"]}
IN_ARCHIVE = {"field": "@path", "op": "glob", "values": ["notes/archive/**"]}
OUTSIDE_LINE = "作業範囲の外（参考）"
OUTSIDE_LOG = "作業範囲の外を読んだ"
OUTSIDE_HINT = "outside_scope: true"
OBJECT_TAGS_CONFIG = (
    "name: sample\n"
    "default_ref: develop\n"
    "documents:\n"
    "  - id: rules\n"
    "    paths: [rules/*.yaml]\n"
    "    schema: schemas/rule.schema.yaml\n"
    '    metadata: {tags: "tags[].name", main_tags: "tags[main].name"}\n'
)
OBJECT_TAGS_SCHEMA = (
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
TAG_MCP = {"field": "tags", "op": "eq", "values": ["mcp"]}
# 配列の中のオブジェクトのキー（`uses[].id`）を持つ種類の配信元
USES_CONFIG = (
    "name: sample\n"
    "default_ref: develop\n"
    "documents:\n"
    "  - id: templates\n"
    "    paths: [templates/*.yaml]\n"
    "    schema: schemas/template.schema.yaml\n"
)
USES_SCHEMA = (
    "type: object\n"
    "properties:\n"
    "  id: {type: string}\n"
    "  name: {type: string}\n"
    "  uses:\n"
    "    type: array\n"
    "    items:\n"
    "      type: object\n"
    "      properties:\n"
    "        id: {type: string}\n"
)
USES_FILES = {
    "project-index.yaml": USES_CONFIG,
    "schemas/template.schema.yaml": USES_SCHEMA,
    "templates/t1.yaml": "id: t1\nname: 素材 1\nuses:\n  - {id: compare}\n  - {id: list}\n",
    "templates/t2.yaml": "id: t2\nname: 素材 2\nuses:\n  - {id: compare-x}\n",
}
MAIN_TAG_MCP = {"field": "main_tags", "op": "eq", "values": ["mcp"]}
NOTES_A = {"field": "id", "op": "eq", "values": ["notes/a.md"]}

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


def _notes_files(
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
    notes: dict[str, str],
    tagged: tuple[str, ...] = (),
) -> dict[str, str]:
    """sample の文書 2 件を除き、管理用の YAML で Markdown を配信する行 `notes` と notes の文書を持つファイル一式を作る。

    管理用の YAML はフォルダごとに `files.yaml` を置き、`tagged` に挙げたファイルにはタグ `x` を付ける。
    """
    indexes: dict[str, list[str]] = {}
    for name in notes:
        folder, _, base = name.rpartition("/")
        tags = "    tags: [x]\n" if name in tagged else ""
        indexes.setdefault(folder, []).append(f"  - path: {base}\n{tags}")
    index_files = {
        f"{folder}/files.yaml": "files:\n" + "".join(rows) for folder, rows in indexes.items()
    }
    files = sample_file_set(
        **{"project-index.yaml": sample_config_text(NOTES_ROWS), **index_files, **notes}
    )
    return {name: text for name, text in files.items() if not name.startswith("docs/")}


def test_normal(make_source: Callable[..., Any], make_server: Callable[..., Any]) -> None:
    """source を省いて作業中の配信元の一覧を返す（正常系）。"""
    # 準備
    source = make_source("sample")
    env = make_server(source)
    # 実行
    result = env.call(
        "search_docs",
        cwd=str(source.folder),
        filter={"field": "kind", "op": "eq", "values": ["sample"]},
        view="summary",
    )
    # 検証
    rows = [line for line in result.text.splitlines() if line.startswith("| doc-")]
    assert not result.is_error
    assert result.text.startswith("sample: 該当 2 件・返却した 2 件")
    assert [row.split("|")[1].strip() for row in rows] == ["doc-1", "doc-2"]
    assert all(re.search(r"\| [0-9a-f]{6} \|$", row) for row in rows)
    assert result.structured is None


def test_normal_when_full(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """ID で絞って view: full で本文を返す（正常系）。"""
    # 準備
    source = make_source("sample")
    env = make_server(source)
    head = run_git(source.folder, "rev-parse", "HEAD").strip()
    folder = source.folder
    arguments = {"cwd": str(folder), "filter": BY_ID, "view": "full"}
    # 実行
    markdown = env.call("search_docs", **arguments)
    as_json = env.call("search_docs", format="json", **arguments)
    cut = env.call("search_docs", format="json", max_chars_per_field=10, **arguments)
    snippets = env.call(
        "search_docs",
        cwd=str(folder),
        filter={"field": "body", "op": "contains", "values": ["文書 1"]},
        view="full",
        snippets={"context_lines": 1, "max_per_doc": 3},
        format="json",
    )
    summary = env.call("search_docs", cwd=str(folder), view="summary", format="json")
    revision = env.call("search_docs", ref=head, **arguments)
    revision_json = env.call("search_docs", ref=head, format="json", **arguments)
    # 検証
    documents = re.findall(r"<document[^>]*>(.*?)</document>", markdown.text, flags=re.S)
    assert len(documents) == 2
    assert "id: doc-2" in documents[0]
    assert "id: doc-1" in documents[1]
    assert f'<document path="{folder}/docs/doc-2.yaml" scope="full">' in markdown.text
    assert f'<document path="{folder}/docs/doc-1.yaml" scope="full">' in markdown.text
    assert as_json.structured is not None
    assert as_json.structured == as_json.data
    assert [item["id"] for item in as_json.data["items"]] == ["doc-2", "doc-1"]
    assert "id: doc-2" in as_json.data["items"][0]["values"]["body"]
    assert [(item["path"], item["scope"]) for item in as_json.data["items"]] == [
        (f"{folder}/docs/doc-2.yaml", "full"),
        (f"{folder}/docs/doc-1.yaml", "full"),
    ]
    assert [item["scope"] for item in cut.data["items"]] == ["section", "section"]
    assert [item["scope"] for item in snippets.data["items"]] == ["section"]
    assert [item["scope"] for item in summary.data["items"]] == ["summary", "summary"]
    assert "<document>" in revision.text
    assert "path=" not in revision.text
    assert all("path" not in item and "scope" not in item for item in revision_json.data["items"])


def test_normal_when_snippets(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """regex を行単位で当て、当たった行を行番号つきの抜粋で返す（正常系）。"""
    # 準備
    doc_1 = "\n".join(
        [
            "id: doc-1",
            "name: 文書 1",
            "## 手順",
            "description: 1 件目",
            "tags: [a]",
            "# 補足",
            "# 補足 2",
            "# 本文の途中の ## は当たらない",
        ]
    )
    source = make_source("sample", sample_file_set(**{"docs/doc-1.yaml": doc_1 + "\n"}))
    env = make_server(source)
    arguments = {
        "cwd": str(source.folder),
        "filter": {"field": "body", "op": "regex", "values": ["^## "]},
        "view": "full",
        "snippets": {"before": 0, "after": 1},
    }
    # 実行
    markdown = env.call("search_docs", **arguments)
    as_json = env.call("search_docs", format="json", **arguments)
    contains = env.call(
        "search_docs",
        cwd=str(source.folder),
        filter={"field": "body", "op": "contains", "values": ["手順"]},
        view="full",
        snippets={"context_lines": 1},
    )
    anchor = env.call(
        "search_docs",
        **{**arguments, "filter": {"field": "body", "op": "regex", "values": ["\\A\\S"]}},
    )
    # 検証
    lines = markdown.text.splitlines()
    item = as_json.data["items"][0]
    assert markdown.text.startswith("sample: 該当 1 件・返却した 1 件")
    assert "3:## 手順" in lines
    assert "4-description: 1 件目" in lines
    assert not any(line.startswith(("2-", "2:", "8-", "8:")) for line in lines)
    assert [entry["id"] for entry in as_json.data["items"]] == ["doc-1"]
    assert len(item["snippets"]) == 1
    assert item["snippets"][0]["lines"] == [
        {"line": 3, "text": "## 手順", "hit": True},
        {"line": 4, "text": "description: 1 件目", "hit": False},
    ]
    assert item["scope"] == "section"
    context_lines = contains.text.splitlines()
    assert context_lines.count("2-name: 文書 1") == 1
    assert context_lines.count("3:## 手順") == 1
    assert context_lines.count("4-description: 1 件目") == 1
    assert "<document" in anchor.text
    assert "1:id: doc-1" in anchor.text.splitlines()


def test_normal_when_count_grouped(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """view: count と group_by で件数と正規化した値ごとの件数だけを返す（正常系）。"""
    # 準備
    doc_2 = sample_doc_text("doc-2", "文書 2", description="2 件目", tags=["a", "Ａ", "b"])
    source = make_source("sample", sample_file_set(**{"docs/doc-2.yaml": doc_2}))
    env = make_server(source)
    # 実行
    result = env.call(
        "search_docs", cwd=str(source.folder), view="count", group_by="tags", format="json"
    )
    # 検証
    assert result.data["total_count"] == 2
    assert result.data["groups"] == [{"value": "a", "count": 2}, {"value": "b", "count": 1}]
    assert not result.data.get("items")


def test_normal_when_ordered_and_limited(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
    commit_all: Callable[..., str],
) -> None:
    """order_by の複数キーで並べ、limit を丸め、max_chars で打ち切る（正常系）。"""
    # 準備
    older = {
        f"docs/a-{n:03d}.yaml": sample_doc_text(f"a-{n:03d}", "旧", description="x" * (100 + n))
        for n in range(1, 61)
    }
    newer = {
        f"docs/b-{n:03d}.yaml": sample_doc_text(f"b-{n:03d}", "新", description="x" * (100 + n))
        for n in range(1, 61)
    }
    files = sample_file_set(**older)
    del files["docs/doc-1.yaml"], files["docs/doc-2.yaml"]
    source = make_source("sample", files, date="2026-01-01T00:00:00+09:00")
    commit_all(source.folder, newer, "docs: 新しい文書", date="2026-02-01T00:00:00+09:00")
    env = make_server(source)
    arguments = {
        "cwd": str(source.folder),
        "order_by": [
            {"field": "updated", "direction": "desc"},
            {"field": "@chars", "direction": "asc"},
        ],
        "format": "json",
    }
    # 実行
    first = env.call("search_docs", limit=150, **arguments)
    second = env.call("search_docs", limit=150, max_chars=500, **arguments)
    third = env.call(
        "search_docs",
        limit=150,
        max_chars=500,
        cursor=second.data["next_cursor"],
        **arguments,
    )
    # 検証
    ids = [item["id"] for item in first.data["items"]]
    assert len(ids) == 100
    assert (ids[0], ids[59], ids[60], ids[99]) == ("b-001", "b-060", "a-001", "a-040")
    assert any("100" in note for note in first.data["notes"])
    assert first.data["next_cursor"]
    assert second.data["truncated"] is True
    assert second.data["next_cursor"]
    assert any("view: ids" in note for note in second.data["notes"])
    second_ids = [item["id"] for item in second.data["items"]]
    third_ids = [item["id"] for item in third.data["items"]]
    assert third_ids
    assert set(second_ids).isdisjoint(third_ids)


def test_normal_when_source_all(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """source: * で参照できる全配信元を横断する（正常系）。"""
    # 準備
    sample = make_source("sample")
    notes = make_source("notes", git=False, scope_read=[sample.folder])
    other = make_source("other", scope_read=[Path("/nonexistent-other")])
    env = make_server(sample, notes, other)
    # 実行
    result = env.call("search_docs", cwd=str(sample.folder), source="*", format="json")
    # 検証
    sources = {item["source"] for item in result.data["items"]}
    assert not result.is_error
    assert sources == {"sample", "notes"}
    assert result.data["per_source"] == {"sample": 2, "notes": 2}


def test_normal_when_worktree(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_doc_text: Callable[..., str],
) -> None:
    """worktree か cwd で指したワークツリーの文書を返す（正常系）。"""
    # 準備
    source = make_source("sample")
    worktree = add_worktree(source.folder, "x")
    (worktree / "docs" / "doc-1.yaml").write_text(
        sample_doc_text("doc-1", "ワークツリーの名前"), encoding="utf-8"
    )
    env = make_server(source)
    arguments = {"filter": DOC_1, "view": "full"}
    # 実行
    by_worktree = env.call(
        "search_docs", cwd=str(source.folder), worktree=str(worktree), **arguments
    )
    by_cwd = env.call("search_docs", cwd=str(worktree), **arguments)
    by_clone = env.call("search_docs", cwd=str(source.folder), **arguments)
    # 検証
    assert "name: ワークツリーの名前" in by_worktree.text
    assert "name: ワークツリーの名前" in by_cwd.text
    assert "name: 文書 1" in by_clone.text
    assert "ワークツリーの名前" not in by_clone.text
    assert f'<document path="{worktree}/docs/doc-1.yaml" scope="full">' in by_worktree.text
    assert f'<document path="{worktree}/docs/doc-1.yaml" scope="full">' in by_cwd.text
    assert f'<document path="{source.folder}/docs/doc-1.yaml" scope="full">' in by_clone.text


def test_normal_when_worktree_adds_row(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_config_text: Callable[..., str],
    sample_doc_text: Callable[..., str],
) -> None:
    """ワークツリーの配信元の設定にだけある documents の行の文書を返す（正常系）。"""
    # 準備
    source = make_source("sample")
    worktree = add_worktree(source.folder, "x")
    env = make_server(source)
    notes_row = "  - id: notes\n    paths: [notes/*.yaml]\n    schema: schemas/sample.schema.yaml\n"
    (worktree / "project-index.yaml").write_text(sample_config_text(notes_row), encoding="utf-8")
    (worktree / "notes").mkdir()
    (worktree / "notes" / "N-1.yaml").write_text(
        sample_doc_text("N-1", "ノート 1"), encoding="utf-8"
    )
    notes = {"field": "kind", "op": "eq", "values": ["notes"]}
    # 実行
    by_worktree = env.call(
        "search_docs", cwd=str(source.folder), worktree=str(worktree), filter=notes, format="json"
    )
    by_cwd = env.call("search_docs", cwd=str(worktree), filter=notes, format="json")
    grouped = env.call(
        "search_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        view="count",
        group_by="kind",
        format="json",
    )
    by_clone = env.call("search_docs", cwd=str(source.folder), filter=notes, format="json")
    # 検証
    assert [item["id"] for item in by_worktree.data["items"]] == ["N-1"]
    assert [item["id"] for item in by_cwd.data["items"]] == ["N-1"]
    assert {"value": "notes", "count": 1} in grouped.data["groups"]
    assert not by_clone.data.get("items")


def test_normal_when_worktree_metadata_changed(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_config_text: Callable[..., str],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """ワークツリーの設定でメタデータの対応を変えると、次の呼び出しから変えた後の対応で返す（正常系）。"""
    # 準備
    refs = [{"to": "doc-2", "type": "references"}]
    files = sample_file_set(**{"docs/doc-1.yaml": sample_doc_text("doc-1", "文書 1", refs=refs)})
    source = make_source("sample", files)
    worktree = add_worktree(source.folder, "x")
    env = make_server(source)
    arguments = {
        "cwd": str(source.folder),
        "filter": {"field": "id", "op": "eq", "values": ["doc-1"]},
        "fields": ["related"],
        "format": "json",
    }
    before = env.call("search_docs", worktree=str(worktree), **arguments)
    # ワークツリーの設定だけ、行の metadata に related: refs を追加し、commit しない
    (worktree / "project-index.yaml").write_text(
        sample_config_text().replace(
            "    schema: schemas/sample.schema.yaml\n",
            "    schema: schemas/sample.schema.yaml\n    metadata:\n      related: refs\n",
        ),
        encoding="utf-8",
    )
    # 実行
    after = env.call("search_docs", worktree=str(worktree), **arguments)
    by_clone = env.call("search_docs", **arguments)
    # 検証
    assert not before.data["items"][0]["values"].get("related")
    assert after.data["items"][0]["values"]["related"] == [{"to": "doc-2", "type": "references"}]
    assert not by_clone.data["items"][0]["values"].get("related")


# `on: [read]` の検査 `check` を行 `sample` に持たせる設定の追記
READ_VALIDATOR = (
    "    validators: [check]\n"
    "validators:\n"
    "  - id: check\n"
    "    run: [python3, scripts/{script}]\n"
    "    on: [read]\n"
)


def _violations_script(rule: str | None) -> str:
    """標準入力を読み、`rule` があればその違反を 1 件出す検査のスクリプトを返す。"""
    found = f'[{{"rule": "{rule}"}}]' if rule else "[]"
    return f"import sys\nsys.stdin.read()\nprint('{found}')\n"


def test_normal_when_worktree_validator_changed(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_config_text: Callable[..., str],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """ワークツリーで読み取りの検査のスクリプトや行を変えると、次の呼び出しから変えた後の違反を返す（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(READ_VALIDATOR.format(script="check.py")),
            "scripts/check.py": _violations_script(None),
            "scripts/check_b.py": _violations_script("rule-b"),
        }
    )
    source = make_source("sample", files)
    worktree = add_worktree(source.folder, "x")
    env = make_server(source)
    arguments = {
        "cwd": str(source.folder),
        "filter": {"field": "id", "op": "eq", "values": ["doc-1"]},
        "format": "json",
    }
    # 実行
    first = env.call("search_docs", worktree=str(worktree), **arguments)
    # ワークツリーのスクリプトだけを書き換え、commit しない
    (worktree / "scripts" / "check.py").write_text(_violations_script("rule-a"), encoding="utf-8")
    second = env.call("search_docs", worktree=str(worktree), **arguments)
    # ワークツリーの設定の行の run だけを変え、commit しない
    (worktree / "project-index.yaml").write_text(
        sample_config_text(READ_VALIDATOR.format(script="check_b.py")), encoding="utf-8"
    )
    third = env.call("search_docs", worktree=str(worktree), **arguments)
    by_clone = env.call("search_docs", **arguments)
    # 検証
    assert not [note for note in first.data.get("notes", []) if note.startswith("doc-1:")]
    assert "doc-1: check: rule-a（$）" in second.data.get("notes", [])
    assert "doc-1: check: rule-b（$）" in third.data.get("notes", [])
    assert not [note for note in third.data.get("notes", []) if "rule-a" in note]
    assert not [note for note in by_clone.data.get("notes", []) if note.startswith("doc-1:")]


def test_error_when_worktree_config_invalid(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_config_text: Callable[..., str],
) -> None:
    """ワークツリーの配信元の設定が検証に通らなければ、違反を添えて断る（異常系）。"""
    # 準備
    source = make_source("sample")
    worktree = add_worktree(source.folder, "x")
    env = make_server(source)
    (worktree / "project-index.yaml").write_text(
        sample_config_text().replace(
            "    paths: [docs/*.yaml]\n", "    paths: [docs/*.yaml]\n    typo: x\n"
        ),
        encoding="utf-8",
    )
    # 実行
    by_worktree = env.call("search_docs", cwd=str(source.folder), worktree=str(worktree))
    by_clone = env.call("search_docs", cwd=str(source.folder), filter=DOC_1)
    # 検証
    assert by_worktree.is_error
    assert "ValidationFailedError" in by_worktree.text
    assert "documents[0].typo" in by_worktree.text
    assert not by_clone.is_error
    assert "doc-1" in by_clone.text


def test_normal_when_seen(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_doc_text: Callable[..., str],
) -> None:
    """同じ会話で同じバージョンの本文を 2 回目は省く（正常系）。"""
    # 準備
    source = make_source("sample")
    env = make_server(source)
    arguments = {"cwd": str(source.folder), "filter": DOC_1, "view": "full"}
    body = "id: doc-1\nname: 文書 1"
    # 実行
    first = env.call("search_docs", session_id="s1", **arguments)
    second = env.call("search_docs", session_id="s1", **arguments)
    second_json = env.call("search_docs", session_id="s1", format="json", **arguments)
    repeated = env.call("search_docs", session_id="s1", repeat_seen=True, **arguments)
    other_session = env.call("search_docs", session_id="s2", **arguments)
    summary = env.call(
        "search_docs", cwd=str(source.folder), session_id="s1", filter=DOC_1, view="summary"
    )
    (source.folder / "docs" / "doc-1.yaml").write_text(
        sample_doc_text("doc-1", "変更後の名前"), encoding="utf-8"
    )
    changed = env.call("search_docs", session_id="s1", **arguments)
    # 検証
    assert body in first.text
    assert "（この会話で返却済み）" in second.text
    assert body not in second.text
    assert "<document>" in second.text
    assert "path=" not in second.text
    assert "path" not in second_json.data["items"][0]
    assert "scope" not in second_json.data["items"][0]
    assert body in repeated.text
    assert body in other_session.text
    assert "1 件目" in summary.text
    assert "id: doc-1\nname: 変更後の名前" in changed.text


def test_normal_when_files_index(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """管理用の YAML の各行を文書にし、名前の既定と本文のファイルの場所を返す（正常系）。"""
    # 準備
    src_row = (
        "  - id: src\n"
        "    paths: [src/files.yaml]\n"
        "    schema: schemas/files.schema.yaml\n"
        "    records: files\n"
        "    body_file: path\n"
    )
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(src_row),
            "schemas/files.schema.yaml": FILES_SCHEMA.read_text(encoding="utf-8"),
            "docs/doc-2.yaml": "id: doc-2\n",
            "src/files.yaml": (
                "files:\n  - path: a.py\n    tags: [auth, code]\n  - path: b.py\n    name: 部品 B\n"
            ),
            "src/a.py": "a = 1\n",
            "src/b.py": "b = 2\n",
        }
    )
    source = make_source("sample", files)
    env = make_server(source)
    # 実行
    one = env.call(
        "search_docs",
        cwd=str(source.folder),
        filter={"field": "id", "op": "eq", "values": ["src/a.py"]},
        view="full",
        format="json",
    )
    markdown = env.call(
        "search_docs",
        cwd=str(source.folder),
        filter={"field": "id", "op": "eq", "values": ["src/a.py"]},
        view="full",
    )
    everything = env.call("search_docs", cwd=str(source.folder), view="summary", format="json")
    # 検証
    item = one.data["items"][0]
    names = {row["id"]: row["values"]["name"] for row in everything.data["items"]}
    assert item["id"] == "src/a.py"
    assert item["values"]["name"] == "a"
    assert item["values"]["tags"] == ["auth", "code"]
    assert item["values"]["path"] == "a.py"
    assert item["path"] == f"{source.folder}/src/a.py"
    assert item["scope"] == "full"
    assert item["values"]["body"] == "a = 1\n"
    assert f'<document path="{source.folder}/src/a.py" scope="full">' in markdown.text
    assert names["src/b.py"] == "部品 B"
    assert names["doc-2"] == "doc-2"
    assert "'files' is a required property" not in one.text
    assert "'files' is a required property" not in everything.text


ABSENT_ROW = (
    "  - id: notes\n"
    "    paths: [notes/index.yaml]\n"
    "    schema: schemas/notes.schema.yaml\n"
    "    records: items\n"
    "    body_file: path\n"
)
ABSENT_SCHEMA = (
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
ABSENT_INDEX = (
    "items:\n"
    "  - id: n1\n    path: n1.md\n"
    "  - title: 本文なし\n"
    "  - id: n3\n    path: ''\n"
    "  - id: n4\n    path: n4.md\n"
    "  - id: n5\n    path: n5.md\n"
)


def test_normal_when_body_file_absent(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """`body_file` の列が無い・空の要素を要素を本文にした文書として返し、無いファイルの知らせを 1 行にまとめる（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(ABSENT_ROW),
            "schemas/notes.schema.yaml": ABSENT_SCHEMA,
            "notes/index.yaml": ABSENT_INDEX,
            "notes/n1.md": "# n1\n",
        }
    )
    source = make_source("sample", files)
    env = make_server(source)
    # 実行
    result = env.call(
        "search_docs",
        cwd=str(source.folder),
        filter={"field": "kind", "op": "eq", "values": ["notes"]},
        view="full",
        format="json",
    )
    # 検証
    items = {item["id"]: item for item in result.data["items"]}
    index_path = f"{source.folder}/notes/index.yaml"
    loading = [note for note in result.data["notes"] if "notes/index.yaml" in note]
    assert not result.is_error
    assert sorted(items) == ["n1", "n3", "notes/index.yaml#1"]
    assert items["n1"]["values"]["body"] == "# n1\n"
    assert items["n1"]["path"] == f"{source.folder}/notes/n1.md"
    assert items["notes/index.yaml#1"]["values"]["body"] == "title: 本文なし\n"
    assert items["notes/index.yaml#1"]["values"]["name"] == "notes/index.yaml#1"
    assert items["n3"]["values"]["body"] == "id: n3\npath: ''\n"
    assert [items[key]["path"] for key in ("notes/index.yaml#1", "n3")] == [index_path] * 2
    assert [items[key]["scope"] for key in ("notes/index.yaml#1", "n3")] == ["section"] * 2
    assert len(loading) == 1
    assert loading[0].startswith(
        "notes/index.yaml の 2 件を読み込めないので除きました（先頭: items[3]"
    )


def test_normal_when_file_unreadable(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """YAML として読めないファイルを除いて返し、notes で知らせる（正常系）。"""
    # 準備
    source = make_source("sample")
    (source.folder / "docs" / "doc-1.yaml").write_text("a: [1\n", encoding="utf-8")
    env = make_server(source)
    # 実行
    result = env.call("search_docs", cwd=str(source.folder), view="summary", format="json")
    # 検証
    notes = " ".join(result.data["notes"])
    assert not result.is_error
    assert [item["id"] for item in result.data["items"]] == ["doc-2"]
    assert "docs/doc-1.yaml" in notes
    assert re.search(r"1.*\d+", notes)


def test_error_when_source_not_readable(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """scope.read に当たらない配信元を指すと断る（異常系）。"""
    # 準備
    sample = make_source("sample")
    other_files = sample_file_set(**{"docs/doc-1.yaml": "id: secret-1\nname: 秘密\n"})
    other = make_source("other", other_files)
    env = make_server(sample, other)
    # 実行
    with_cwd = env.call("search_docs", cwd=str(sample.folder), source="other")
    without_cwd = env.call("search_docs", source="other")
    # 検証
    for result in (with_cwd, without_cwd):
        assert result.is_error
        assert "other" in result.text
        assert "SourceNotReadableError" in result.text
        assert "secret-1" not in result.text
    assert "sample" in with_cwd.text


def test_error_when_source_not_served(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """起動時の検証で外した配信元を指すと、外した理由を返す（異常系）。"""
    # 準備
    sample = make_source("sample")
    broken = make_source(
        "broken", {"project-index.yaml": BROKEN_CONFIG}, scope_read=[sample.folder]
    )
    env = make_server(sample, broken)
    # 実行
    result = env.call("search_docs", cwd=str(sample.folder), source="broken")
    # 検証
    assert result.is_error
    assert "SourceNotServedError" in result.text
    assert "broken" in result.text
    assert "documents[0].paths" in result.text


def test_error_when_worktree_not_matched(
    make_source: Callable[..., Any], make_server: Callable[..., Any], tmp_path: Path
) -> None:
    """worktrees に当たらない worktree を断る（異常系）。"""
    # 準備
    source = make_source("sample")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    env = make_server(source)
    # 実行
    result = env.call("search_docs", cwd=str(source.folder), worktree=str(elsewhere))
    # 検証
    assert result.is_error
    assert "WorktreeNotMatchedError" in result.text
    assert str(elsewhere) in result.text
    assert ".claude/worktrees" in result.text


def test_error_when_invalid_argument(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """スキーマに無い項目や型の合わない値を、直し方を添えて断る（異常系）。"""
    # 準備
    source = make_source("sample")
    env = make_server(source)
    # 実行
    unknown_field = env.call(
        "search_docs",
        cwd=str(source.folder),
        filter={"field": "nme", "op": "eq", "values": ["x"]},
    )
    bad_value = env.call(
        "search_docs",
        cwd=str(source.folder),
        filter={"field": "weight", "op": "gt", "values": ["abc"]},
    )
    both_keys = env.call(
        "search_docs",
        cwd=str(source.folder),
        filter={"and": [DOC_1], "not": {"field": "tags", "op": "eq", "values": ["x"]}},
    )
    matches_condition = env.call(
        "search_docs",
        cwd=str(source.folder),
        filter={"field": "@matches", "op": "gt", "values": ["1"]},
    )
    sections_and_lines = env.call(
        "search_docs",
        cwd=str(source.folder),
        view="full",
        sections=["a"],
        lines={"offset": 1},
    )
    sections_in_summary = env.call(
        "search_docs", cwd=str(source.folder), view="summary", sections=["a"]
    )
    uses = make_source("uses", USES_FILES)
    dotted = make_server(uses).call(
        "search_docs",
        cwd=str(uses.folder),
        filter={"field": "uses.id", "op": "eq", "values": ["compare"]},
    )
    # 検証
    assert unknown_field.is_error
    assert "InvalidArgumentError" in unknown_field.text
    assert "filter.field" in unknown_field.text
    assert "nme" in unknown_field.text
    assert "describe" in unknown_field.text
    assert bad_value.is_error
    assert "abc" in bad_value.text
    assert "number" in bad_value.text
    assert both_keys.is_error
    assert "and・or・not のどれか 1 つだけを持ってください" in both_keys.text
    assert matches_condition.is_error
    assert "@matches は条件に使用できません" in matches_condition.text
    assert sections_and_lines.is_error
    assert "sections と lines は同時に指定できません" in sections_and_lines.text
    assert sections_in_summary.is_error
    assert "view: full のときだけ指定できます" in sections_in_summary.text
    # 配列の中のキーを `.` で指すと、近い項目の候補に `uses[].id` を返却する
    assert dotted.is_error
    assert "知らない項目です（uses.id）" in dotted.text
    assert "uses[].id" in dotted.text


def test_error_when_ref_not_found(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """解決できない ref を断る（異常系）。"""
    # 準備
    sample = make_source("sample")
    notes = make_source("notes", git=False, scope_read=[sample.folder])
    env = make_server(sample, notes)
    # 実行
    no_ref = env.call("search_docs", cwd=str(sample.folder), ref="no-such-branch")
    non_git = env.call("search_docs", cwd=str(sample.folder), source="notes", ref="develop")
    # 検証
    assert no_ref.is_error
    assert "RefNotFoundError" in no_ref.text
    assert "no-such-branch" in no_ref.text
    assert non_git.is_error
    assert "ref" in non_git.text


def test_normal_when_excluded_name(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """行の exclude に当たるファイルをその行の文書にせず、他の行に当たればその行の文書として返す（正常系）。"""
    # 準備
    rows = (
        "  - id: rule\n"
        "    paths: [docs/rule/*.yaml]\n"
        "    schema: schemas/sample.schema.yaml\n"
        "    exclude: [index.yaml]\n"
        "  - id: index\n"
        "    paths: [docs/**/index.yaml]\n"
        "    schema: schemas/sample.schema.yaml\n"
    )
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(rows),
            "docs/rule/a.yaml": "id: a\nname: a\n",
            "docs/rule/Rb.yaml": "id: Rb\nname: Rb\n",
            "docs/rule/index.yaml": "id: rule-index\nname: 目次\n",
        }
    )
    source = make_source("sample", files)
    env = make_server(source)
    # 実行
    rule = env.call(
        "search_docs",
        cwd=str(source.folder),
        filter={"field": "kind", "op": "eq", "values": ["rule"]},
        view="summary",
        format="json",
    )
    index = env.call(
        "search_docs",
        cwd=str(source.folder),
        filter={"field": "kind", "op": "eq", "values": ["index"]},
        view="summary",
        format="json",
    )
    # 検証
    assert [item["id"] for item in rule.data["items"]] == ["a", "Rb"]
    assert [item["id"] for item in index.data["items"]] == ["rule-index"]


def test_normal_when_ordered_by_matches(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """not・glob で絞り、@matches を返してよく当たる順に並べる（正常系）。"""
    # 準備
    notes = {
        "notes/a.md": "検索 1\n検索 2\n検索 3\n他\n",
        "notes/b.md": "検索 1\n他\n",
        "notes/archive/c.md": "検索 1\n検索 2\n他\n",
    }
    files = _notes_files(sample_file_set, sample_config_text, notes, tagged=("notes/a.md",))
    source = make_source("sample", files)
    env = make_server(source)
    cwd = str(source.folder)
    exclude_archive = {"and": [SEARCH_WORD, {"not": IN_ARCHIVE}]}
    by_matches = {"fields": ["@matches"], "order_by": [{"field": "@matches", "direction": "desc"}]}
    # 実行
    ordered = env.call("search_docs", cwd=cwd, filter=exclude_archive, format="json", **by_matches)
    without_not = env.call("search_docs", cwd=cwd, filter=SEARCH_WORD, format="json", **by_matches)
    direct_only = env.call(
        "search_docs",
        cwd=cwd,
        filter={"field": "@path", "op": "glob", "values": ["notes/files.yaml#*"]},
        format="json",
    )
    under_not = env.call(
        "search_docs",
        cwd=cwd,
        filter={"not": {"and": [SEARCH_WORD, {"field": "tags", "op": "eq", "values": ["x"]}]}},
        fields=["@matches"],
        format="json",
    )
    without_fields = env.call("search_docs", cwd=cwd, filter=exclude_archive, format="json")
    # 検証
    assert [(item["id"], item["values"]["@matches"]) for item in ordered.data["items"]] == [
        ("notes/a.md", 3),
        ("notes/b.md", 1),
    ]
    assert [(item["id"], item["values"]["@matches"]) for item in without_not.data["items"]] == [
        ("notes/a.md", 3),
        ("notes/archive/c.md", 2),
        ("notes/b.md", 1),
    ]
    assert [item["id"] for item in direct_only.data["items"]] == ["notes/a.md", "notes/b.md"]
    assert [(item["id"], item["values"]["@matches"]) for item in under_not.data["items"]] == [
        ("notes/archive/c.md", 0),
        ("notes/b.md", 0),
    ]
    assert all("@matches" not in item["values"] for item in without_fields.data["items"])


def test_normal_when_part_of_body(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """sections・lines で本文の一部を返し、返却済みに記録しない（正常系）。"""
    # 準備
    lines = [
        "# a",
        "2 行目 検索",
        "## 経緯",
        "経緯の本文",
        "",
        "## 決まったこと",
        "7 行目 検索",
        "詳細",
        "## 残り",
        "残りの本文",
    ]
    text = "\n".join(lines) + "\n"
    files = _notes_files(sample_file_set, sample_config_text, {"notes/a.md": text})
    source = make_source("sample", files)
    env = make_server(source)
    request = {"cwd": str(source.folder), "filter": NOTES_A, "view": "full", "session_id": "s1"}
    decided = "## 決まったこと\n7 行目 検索\n詳細"
    # 実行
    by_section = env.call("search_docs", format="json", sections=["決まったこと"], **request)
    by_lines = env.call("search_docs", format="json", lines={"offset": 3, "limit": 2}, **request)
    whole = env.call("search_docs", format="json", **request)
    again = env.call("search_docs", format="json", sections=["決まったこと"], **request)
    snippeted = env.call(
        "search_docs",
        cwd=str(source.folder),
        filter=SEARCH_WORD,
        view="full",
        sections=["決まったこと"],
        snippets={"context_lines": 0},
        format="json",
    )
    missing = env.call("search_docs", format="json", sections=["無い見出し"], **request)
    markdown = env.call("search_docs", sections=["決まったこと"], **request)
    # 検証
    first = by_section.data["items"][0]
    assert first["values"]["body"] == decided
    assert first["scope"] == "section"
    assert first["ranges"] == [{"start_line": 6, "end_line": 8}]
    assert first["total_lines"] == 10
    assert by_lines.data["items"][0]["values"]["body"] == "## 経緯\n経緯の本文"
    assert by_lines.data["items"][0]["ranges"] == [{"start_line": 3, "end_line": 4}]
    assert whole.data["items"][0]["values"]["body"] == text
    assert whole.data["items"][0]["scope"] == "full"
    assert "ranges" not in whole.data["items"][0]
    assert "total_lines" not in whole.data["items"][0]
    assert again.data["items"][0]["values"]["body"] == decided
    assert snippeted.data["items"][0]["snippets"][0]["lines"] == [
        {"line": 7, "text": "7 行目 検索", "hit": True}
    ]
    assert missing.data["items"][0]["values"].get("body", "") == ""
    assert missing.data["items"][0]["ranges"] == []
    assert any("無い見出し" in note for note in missing.data["notes"])
    assert "notes/a.md: 6-8 行目 / 全 10 行" in markdown.text


def test_normal_when_metadata_mapped(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """列名の違う種類を共通のキーで引く（正常系）。"""
    # 準備
    row = (
        "  - id: decisions\n"
        "    paths: [decisions/*.yaml]\n"
        "    schema: schemas/decision.schema.yaml\n"
        "    metadata: {name: title, description: meta.summary}\n"
    )
    schema = (
        "type: object\n"
        "properties:\n"
        "  id: {type: string}\n"
        "  title: {type: string}\n"
        "  meta:\n"
        "    type: object\n"
        "    properties:\n"
        "      summary: {type: string}\n"
    )
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(row),
            "schemas/decision.schema.yaml": schema,
            "decisions/d1.yaml": "id: d1\ntitle: 決定 1\nmeta:\n  summary: 要約 1\n",
        }
    )
    source = make_source("sample", files)
    env = make_server(source)
    cwd = str(source.folder)
    # 実行
    by_name = env.call(
        "search_docs",
        cwd=cwd,
        filter={"field": "name", "op": "eq", "values": ["決定 1"]},
        view="summary",
        format="json",
    )
    by_column = env.call(
        "search_docs",
        cwd=cwd,
        filter={"field": "title", "op": "eq", "values": ["決定 1"]},
        view="summary",
        format="json",
    )
    # 検証
    assert [item["id"] for item in by_name.data["items"]] == ["d1"]
    assert by_name.data["items"][0]["values"]["name"] == "決定 1"
    assert by_name.data["items"][0]["values"]["description"] == "要約 1"
    assert [item["id"] for item in by_column.data["items"]] == ["d1"]


def _outside_logs(caplog: pytest.LogCaptureFixture) -> list[str]:
    """要求のログのうち作業範囲の外を読んだ記録を返す。"""
    return [record.getMessage() for record in caplog.records if OUTSIDE_LOG in record.getMessage()]


def _other_files(
    sample_file_set: Callable[..., dict[str, str]], sample_doc_text: Callable[..., str]
) -> dict[str, str]:
    """文書 o-1・o-2 を持つ配信元 other のファイル一式を返す。"""
    return sample_file_set(
        **{
            "docs/doc-1.yaml": sample_doc_text("o-1", "other 1"),
            "docs/doc-2.yaml": sample_doc_text("o-2", "other 2"),
        }
    )


def test_normal_when_outside_scope(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """outside_scope: true で、scope に当たらない配信元の文書を作業範囲の外として返す（正常系）。"""
    # 準備
    sample = make_source("sample")
    other = make_source("other", _other_files(sample_file_set, sample_doc_text))
    env = make_server(sample, other)
    cwd = str(sample.folder)
    caplog.set_level(logging.INFO)
    # 実行
    full = env.call("search_docs", cwd=cwd, source="other", outside_scope=True, view="full")
    as_json = env.call("search_docs", cwd=cwd, source="other", outside_scope=True, format="json")
    everything = env.call(
        "search_docs", cwd=cwd, source="*", outside_scope=True, view="ids", format="json"
    )
    # 検証
    assert not full.is_error
    assert full.text.splitlines()[0] == OUTSIDE_LINE
    assert full.text.count('outside_scope="true"') == 2
    assert as_json.data["outside_scope"] is True
    assert {item["id"] for item in as_json.data["items"]} == {"o-1", "o-2"}
    assert any(cwd in message and "other" in message for message in _outside_logs(caplog))
    assert {item["id"] for item in everything.data["items"]} == {"doc-1", "doc-2"}


def test_error_when_outside_read_disabled(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """outside_read: false の配信元は outside_scope: true でも断る（異常系）。"""
    # 準備
    sample = make_source("sample")
    closed = make_source("other", outside_read=False)
    opened = make_source("open")
    env = make_server(sample, closed, opened)
    cwd = str(sample.folder)
    caplog.set_level(logging.INFO)
    # 実行
    refused = env.call("search_docs", cwd=cwd, source="other", outside_scope=True)
    guided = env.call("search_docs", cwd=cwd, source="open")
    # 検証
    assert refused.is_error
    assert "SourceNotReadableError" in refused.text
    assert "other" in refused.text
    assert OUTSIDE_HINT not in refused.text
    assert _outside_logs(caplog) == []
    assert guided.is_error
    assert OUTSIDE_HINT in guided.text


def _term_ids(env: Any, cwd: str, term: str) -> list[str]:
    """term で引いた文書の ID を並べる。"""
    result = env.call("search_docs", cwd=cwd, term=term, view="ids", format="json")
    return [item["id"] for item in result.data.get("items", [])]


def test_normal_when_term(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    alias_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """term で alias_type を持つ行の文書を name・aliases の語で引く（正常系）。"""
    # 準備
    doc_1 = sample_doc_text("doc-1", "担当範囲の文書", description="担当範囲の説明")
    sample = make_source("sample", alias_file_set(**{"docs/doc-1.yaml": doc_1}))
    plain = make_source("plain")
    env = make_server(sample, plain)
    cwd = str(sample.folder)
    # 実行
    by_alias = _term_ids(env, cwd, "担当範囲")
    by_name = _term_ids(env, cwd, "作業範囲")
    by_upper = _term_ids(env, cwd, "SCOPE")
    by_part = _term_ids(env, cwd, "担当")
    no_rows = env.call(
        "search_docs", cwd=str(plain.folder), term="担当範囲", view="ids", format="json"
    )
    # 検証
    assert by_alias == ["scope"]
    assert by_name == ["scope"]
    assert by_upper == ["scope"]
    assert by_part == []
    assert not no_rows.data.get("items")
    assert any("alias_type" in note for note in no_rows.data["notes"])


def test_normal_when_tags_are_objects(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """tags[].name で取り出したタグと main_tags で絞り、数える（正常系）。"""
    # 準備
    files = {
        "project-index.yaml": OBJECT_TAGS_CONFIG,
        "schemas/rule.schema.yaml": OBJECT_TAGS_SCHEMA,
        "rules/r1.yaml": (
            "id: r1\nname: 規約 1\ntags:\n  - {name: mcp, main: true}\n  - {name: 設計}\n"
        ),
        "rules/r2.yaml": (
            "id: r2\nname: 規約 2\ntags:\n  - {name: MCP}\n  - {name: 設計, main: true}\n"
        ),
    }
    source = make_source("sample", files)
    env = make_server(source)
    cwd = str(source.folder)
    # 実行
    by_tags = env.call("search_docs", cwd=cwd, filter=TAG_MCP, view="ids", format="json")
    by_main = env.call("search_docs", cwd=cwd, filter=MAIN_TAG_MCP, view="ids", format="json")
    counted = env.call("search_docs", cwd=cwd, view="count", group_by="tags", format="json")
    picked = env.call(
        "search_docs",
        cwd=cwd,
        filter={"field": "id", "op": "eq", "values": ["r1"]},
        fields=["tags", "main_tags"],
        format="json",
    )
    # 検証
    assert [item["id"] for item in by_tags.data["items"]] == ["r1", "r2"]
    assert [item["id"] for item in by_main.data["items"]] == ["r1"]
    # 表記違いの mcp・MCP は 1 つにまとめる（表記は同数なら値の昇順で先のもの）
    assert counted.data["groups"] == [{"value": "MCP", "count": 2}, {"value": "設計", "count": 2}]
    values = picked.data["items"][0]["values"]
    assert values["tags"] == ["mcp", "設計"]
    assert values["main_tags"] == ["mcp"]


def test_normal_when_array_item_keys(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """配列の中のオブジェクトのキーを uses[].id で指し、要素ごとの値で完全一致で絞り、数える（正常系）。"""
    # 準備
    source = make_source("sample", USES_FILES)
    env = make_server(source)
    cwd = str(source.folder)
    # 実行
    compare = env.call(
        "search_docs",
        cwd=cwd,
        filter={"field": "uses[].id", "op": "eq", "values": ["compare"]},
        view="ids",
        format="json",
    )
    both = env.call(
        "search_docs",
        cwd=cwd,
        filter={"field": "uses[].id", "op": "eq", "values": ["compare", "list"], "match": "all"},
        view="ids",
        format="json",
    )
    counted = env.call("search_docs", cwd=cwd, view="count", group_by="uses[].id", format="json")
    picked = env.call(
        "search_docs",
        cwd=cwd,
        filter={"field": "id", "op": "eq", "values": ["t1"]},
        order_by=[{"field": "uses[].id"}],
        fields=["uses[].id"],
        format="json",
    )
    # 検証
    # compare は compare-x に部分一致しない
    assert [item["id"] for item in compare.data["items"]] == ["t1"]
    assert [item["id"] for item in both.data["items"]] == ["t1"]
    assert counted.data["groups"] == [
        {"value": "compare", "count": 1},
        {"value": "compare-x", "count": 1},
        {"value": "list", "count": 1},
    ]
    assert not picked.is_error
    assert picked.data["items"][0]["values"]["uses[].id"] == ["compare", "list"]


def test_normal_when_relative_ref_in_defs(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """$defs の中の相対パスの参照を解決して検査し、文書を返す（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "schemas/sample.schema.yaml": DEFS_REF_SCHEMA,
            "schemas/common.schema.yaml": COMMON_SCHEMA,
            "docs/doc-1.yaml": sample_doc_text("doc-1", "文書 1", entries=ENTRIES),
        }
    )
    source = make_source("sample", files)
    env = make_server(source)
    # 実行
    result = env.call("search_docs", cwd=str(source.folder), filter=DOC_1, format="json")
    # 検証
    assert not result.is_error
    assert [item["id"] for item in result.data["items"]] == ["doc-1"]
    assert [note for note in result.data.get("notes", []) if note.startswith("doc-1:")] == []


def test_normal_when_cyclic_ref_in_other_file(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """別のファイルの中で循環する参照をそのファイルの定義を指したまま検査し、文書を返す（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "schemas/sample.schema.yaml": TREE_REF_SCHEMA,
            "schemas/common.schema.yaml": TREE_COMMON_SCHEMA,
            "docs/doc-1.yaml": sample_doc_text("doc-1", "文書 1", tree=TREE),
        }
    )
    source = make_source("sample", files)
    env = make_server(source)
    # 実行
    result = env.call("search_docs", cwd=str(source.folder), filter=DOC_1, format="json")
    # 検証
    assert not result.is_error
    assert [item["id"] for item in result.data["items"]] == ["doc-1"]
    assert [note for note in result.data.get("notes", []) if note.startswith("doc-1:")] == []


def test_normal_when_schema_ref_unresolvable(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """スキーマの参照先が無い文書も返し、解決できなかった参照を notes で知らせる（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "schemas/sample.schema.yaml": MISSING_REF_SCHEMA,
            "docs/doc-1.yaml": sample_doc_text("doc-1", "文書 1", entries=ENTRIES),
        }
    )
    source = make_source("sample", files)
    env = make_server(source)
    # 実行
    result = env.call("search_docs", cwd=str(source.folder), filter=DOC_1, format="json")
    # 検証
    notes = " ".join(result.data["notes"])
    assert not result.is_error
    assert [item["id"] for item in result.data["items"]] == ["doc-1"]
    assert "doc-1:" in notes
    assert MISSING_REF in notes
    assert "schemas/sample.schema.yaml" in notes


LOADED_LOG = "ワークツリーを読み込んだ"
# ワークツリーの読み込みを待つ間に、同じ呼び出しを送り直す回数と間隔
LOADING_RETRIES = 30
LOADING_RETRY_SEC = 1


def _put_git(folder: Path, body: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """`body` を実行してから本物の git を実行する `git` のスクリプトを、PATH の先頭に置く。"""
    real = shutil.which("git")
    assert real is not None
    folder.mkdir(parents=True)
    script = folder / "git"
    script.write_text(f'#!/bin/sh\n{body}\nexec "{real}" "$@"\n', encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")


def _loaded_logs(caplog: pytest.LogCaptureFixture, worktree: Path) -> list[str]:
    """ワークツリーを読み込んだログの行のうち、`worktree` のものを返す。"""
    return [
        record.getMessage()
        for record in caplog.records
        if LOADED_LOG in record.getMessage() and str(worktree) in record.getMessage()
    ]


def _call_until_loaded(env: Any, **arguments: Any) -> Any:
    """読み込み中のエラーでなくなるまで、同じ `search_docs` を間を空けて送り直す。"""
    result = env.call("search_docs", **arguments)
    for _ in range(LOADING_RETRIES):
        if "WorktreeLoadingError" not in result.text:
            return result
        time.sleep(LOADING_RETRY_SEC)
        result = env.call("search_docs", **arguments)
    return result


def test_normal_when_new_worktree(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """サーバーの起動後に作ったワークツリーを 1 回だけ読み込み、2 回目以降の呼び出しは読み込んだ内容で返却する（正常系）。"""
    # 準備
    extra = {
        f"docs/extra-{index}.yaml": sample_doc_text(f"extra-{index}", "追加")
        for index in range(500)
    }
    source = make_source("sample", sample_file_set(**extra))
    env = make_server(source)
    worktree = add_worktree(source.folder, "y")
    (worktree / "docs" / "doc-1.yaml").write_text(
        sample_doc_text("doc-1", "ワークツリーの名前"), encoding="utf-8"
    )
    caplog.set_level(logging.INFO)
    common = {"cwd": str(source.folder), "worktree": str(worktree)}
    wait_sec = env.handlers.terminal.worktree_load_wait_sec
    # 実行
    timings: list[float] = []
    started = time.monotonic()
    ids = env.call("search_docs", view="ids", **common)
    timings.append(time.monotonic() - started)
    started = time.monotonic()
    summary = env.call("search_docs", view="summary", **common)
    timings.append(time.monotonic() - started)
    started = time.monotonic()
    full = env.call("search_docs", view="full", filter=DOC_1, **common)
    timings.append(time.monotonic() - started)
    logs_after_three = _loaded_logs(caplog, worktree)
    (worktree / "docs" / "doc-2.yaml").write_text(
        sample_doc_text("doc-2", "書き換えた名前"), encoding="utf-8"
    )
    changed = env.call(
        "search_docs",
        view="full",
        filter={"field": "id", "op": "eq", "values": ["doc-2"]},
        **common,
    )
    # 検証
    assert [ids.is_error, summary.is_error, full.is_error] == [False, False, False]
    assert max(timings) < wait_sec
    assert len(logs_after_three) == 1
    assert "name: ワークツリーの名前" in full.text
    assert "name: 書き換えた名前" in changed.text


def test_error_when_worktree_loading(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_doc_text: Callable[..., str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ワークツリーの読み込みが待ちの上限までに終了しなければ、読み込みを続けたまま読み込み中である旨を返却する（異常系）。"""
    # 準備
    source = make_source("sample")
    env = make_server(source, settings_extra="worktree_load_wait_sec: 1\n")
    worktree = add_worktree(source.folder, "y")
    (worktree / "docs" / "doc-1.yaml").write_text(
        sample_doc_text("doc-1", "ワークツリーの名前"), encoding="utf-8"
    )
    _put_git(tmp_path / "bin", f'case "$PWD" in "{worktree}"*) sleep 3;; esac', monkeypatch)
    caplog.set_level(logging.INFO)
    arguments = {
        "cwd": str(source.folder),
        "worktree": str(worktree),
        "view": "summary",
        "filter": DOC_1,
    }
    # 実行
    started = time.monotonic()
    first = env.call("search_docs", **arguments)
    elapsed = time.monotonic() - started
    finished = time.monotonic()
    loaded = _call_until_loaded(env, **arguments)
    waited = time.monotonic() - finished
    # 検証
    assert first.is_error is True
    assert first.text.startswith(f"WorktreeLoadingError: {worktree} を読み込み中です")
    assert "時間を空けて同じ呼び出しを再実行してください" in first.text
    assert "文書 1" not in first.text
    assert elapsed < 3
    assert loaded.is_error is False
    assert "ワークツリーの名前" in loaded.text
    assert waited < 30
    assert len(_loaded_logs(caplog, worktree)) == 1


def test_error_when_unexpected(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`ProjectIndexError` でない例外を、例外の型と内容を持つ `isError` の応答にする（異常系）。"""
    # 準備
    source = make_source("sample")
    previous = run_git(source.folder, "rev-parse", "HEAD").strip()
    (source.folder / "docs" / "doc-3.yaml").write_text(
        "id: doc-3\nname: 文書 3\n", encoding="utf-8"
    )
    run_git(source.folder, "add", "-A")
    run_git(source.folder, "commit", "-m", "文書 3")
    env = make_server(source)
    _put_git(
        tmp_path / "bin",
        'for arg in "$@"; do [ "$arg" = archive ] && { echo "fatal: archive failed" >&2; exit 128; }; done',
        monkeypatch,
    )
    caplog.set_level(logging.ERROR)
    # 実行
    result = env.call("search_docs", cwd=str(source.folder), ref=previous, view="summary")
    without_ref = env.call("search_docs", cwd=str(source.folder), view="summary")
    # 検証
    assert result.is_error is True
    assert result.text.startswith("UnexpectedError: GitError:")
    assert "git archive" in result.text
    assert "fatal: archive failed" in result.text
    assert not result.text.startswith("Error executing tool")
    assert "ツールの処理に失敗した（search_docs）" in caplog.text
    assert "Traceback" in caplog.text
    assert without_ref.is_error is False
    assert "doc-3" in without_ref.text


def test_normal_when_disk_storage(
    git_repo: Callable[..., Path],
    write_files: Callable[[Path, dict[str, str]], None],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """disk の配信元はワークツリーに読み替えず、登録したフォルダの文書と文書の日時を返す（正常系）。"""
    # 準備（project-index のファイルは commit せず、ワークツリーは持たない）
    folder = git_repo({"README.md": "# company\n"}, name="company")
    stamped = sample_doc_text(
        "doc-1", "文書 1", created="2026-11-01T00:00:00+00:00", updated="2026-11-02T00:00:00+00:00"
    )
    write_files(folder, sample_file_set(**{"docs/doc-1.yaml": stamped}))
    worktree = add_worktree(folder, "x")
    company = SourceSpec(
        id="company",
        folder=folder,
        config=[folder / "project-index.yaml"],
        # disk の配信元はワークツリーを配信元のフォルダとみなさないため、配下も参照できるようにする
        scope_read=[folder / "**"],
        storage="disk",
    )
    env = make_server(company)
    # 実行
    result = env.call(
        "search_docs",
        cwd=str(worktree),
        source="company",
        view="full",
        fields=["id", "created", "updated"],
        format="json",
    )
    # 検証
    rows = {item["id"]: item for item in result.data["items"]}
    assert not result.is_error
    assert {item["path"] for item in result.data["items"]} == {
        f"{folder}/docs/doc-1.yaml",
        f"{folder}/docs/doc-2.yaml",
    }
    assert str(rows["doc-1"]["values"]["created"]).startswith("2026-11-01")
    assert str(rows["doc-1"]["values"]["updated"]).startswith("2026-11-02")
    assert not rows["doc-2"]["values"].get("created")
    assert not rows["doc-2"]["values"].get("updated")


def test_error_when_ref_given_to_disk_source(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
) -> None:
    """disk の配信元への ref・worktree の指定を断る（異常系）。"""
    # 準備
    company = make_source("company", storage="disk")
    worktree = add_worktree(company.folder, "x")
    env = make_server(company)
    cwd = str(company.folder)
    # 実行
    by_ref = env.call("search_docs", cwd=cwd, source="company", ref="develop")
    by_worktree = env.call("search_docs", cwd=cwd, source="company", worktree=str(worktree))
    # 検証
    assert by_ref.is_error
    assert "company は disk の配信元のため ref を指定できません" in by_ref.text
    assert by_worktree.is_error
    assert "company は disk の配信元のため worktree を指定できません" in by_worktree.text


def test_normal_when_builtin_source_read(
    make_builtin_clone: Callable[[], Path],
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
) -> None:
    """組み込みの配信元の手順のページを、outside_scope: true と sections で一部のセクションだけ返す（正常系）。"""
    # 準備
    make_builtin_clone()
    sample = make_source("sample")
    env = make_server(sample)
    cwd = str(sample.folder)
    criteria = {"field": "id", "op": "eq", "values": ["docs/guide/メタデータを付ける基準.md"]}
    # 実行
    part = env.call(
        "search_docs",
        cwd=cwd,
        source="project-index",
        outside_scope=True,
        filter=criteria,
        view="full",
        sections=["仮のメタデータ"],
    )
    refused = env.call("search_docs", cwd=cwd, source="project-index", filter=criteria)
    everything = env.call(
        "search_docs", cwd=cwd, source="*", outside_scope=True, view="ids", format="json"
    )
    # 検証
    assert not part.is_error
    assert part.text.splitlines()[0] == OUTSIDE_LINE
    assert "仮のメタデータの段階" in part.text
    assert "関連の候補の表" not in part.text
    assert refused.is_error
    assert "SourceNotReadableError" in refused.text
    assert "outside_scope: true" in refused.text
    assert {item["id"] for item in everything.data["items"]} == {"doc-1", "doc-2"}


def test_normal_when_direct_commit_workplace(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    commit_all: Callable[..., str],
) -> None:
    """直コミットを呼べる作業場所から読む（正常系）。"""
    # 準備
    direct = make_direct_commit_source(files={"rules/r1.yaml": "id: r1\nname: 規約 1\n"})
    commit_all(direct.develop, {"notes/d1.yaml": "id: d1\nname: develop だけの文書\n"})
    env = make_server(direct.spec)
    # 実行
    found = env.call(
        "search_docs", cwd=str(direct.local), source="sample", view="ids", format="json"
    )
    other = env.call("search_docs", cwd=str(direct.local), source="sample", worktree=str(direct.x))
    # 検証
    text = found.text
    assert not found.is_error, text
    assert "d1" in text
    assert "r1" in text
    assert other.is_error
    assert "コミットするブランチのワークツリーだけ" in other.text

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

import pytest
from project_index.features.documents.store import DocumentStore
from project_index.features.history.snapshot import SnapshotStore
from project_index.features.search.service import search_docs
from project_index.features.search.types import (
    SUMMARY_FIELDS,
    BodyRange,
    Condition,
    Group,
    GroupCount,
    LineRange,
    OrderKey,
    SearchRequest,
    SearchResult,
    Snippet,
    SnippetLine,
    Snippets,
)
from project_index.features.seen.store import SeenStore
from project_index.features.seen.types import SEEN_MARK
from project_index.features.sources.types import (
    DocumentTable,
    ScriptEntry,
    ServedSource,
    SourceConfig,
)
from project_index.features.validation.service import DocumentChecker
from project_index.shared.errors import InvalidArgumentError
from project_index.shared.yaml_io import load_yaml

from tests.unit.project_index.conftest import records_files_schema

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.sources.registry import SourceRegistry

TODAY = date(2026, 10, 28)


@dataclass
class SearchEnv:
    """検索に渡す部品と、作業場所に当たる配信元のフォルダ。"""

    registry: SourceRegistry
    store: DocumentStore
    checker: DocumentChecker
    seen: SeenStore
    root: Path

    def search(self, **request: Any) -> SearchResult:
        return search_docs(
            SearchRequest(cwd=str(self.root), **request),
            registry=self.registry,
            store=self.store,
            checker=self.checker,
            seen=self.seen,
            today=TODAY,
        )


@pytest.fixture
def make_env(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> Callable[..., SearchEnv]:
    """文書のファイルを置いた配信元 sample と、検索に渡す部品を作る関数を返す。"""

    def _make(
        files: dict[str, str],
        *,
        validators: list[ScriptEntry] | None = None,
        row_validators: list[str] | None = None,
        extra_sources: list[ServedSource] | None = None,
        documents: list[DocumentTable] | None = None,
        schemas: dict[str, dict[str, Any]] | None = None,
    ) -> SearchEnv:
        root = tmp_path / "sample"
        write_files(root, files)
        table = DocumentTable(
            id="rules",
            paths=["docs/*.yaml"],
            schema_path="schemas/rule.schema.yaml",
            validators=row_validators or [],
        )
        config = make_source_config(documents=documents or [table], validators=validators or [])
        source = make_served_source(id="sample", root=root, config=config, schemas=schemas or {})
        store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
        checker = DocumentChecker(store, timeout_sec=10)
        seen = SeenStore(tmp_path / "seen.sqlite3", retention_days=7)
        registry = make_registry(source, *(extra_sources or []))
        return SearchEnv(registry, store, checker, seen, root)

    return _make


TWO_DOCS = {
    "docs/doc-1.yaml": "id: doc-1\nname: 文書 1\ndescription: 1 件目\n",
    "docs/doc-2.yaml": "id: doc-2\nname: 文書 2\ndescription: 2 件目\n",
}


def _notes_table() -> DocumentTable:
    """管理用の YAML で Markdown を配信する文書の行を返す。"""
    return DocumentTable(
        id="notes",
        paths=["notes/**/files.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="files",
        body_file="path",
    )


def _yaml_table() -> DocumentTable:
    """YAML の文書の行を返す。"""
    return DocumentTable(id="rules", paths=["docs/*.yaml"], schema_path="schemas/rule.schema.yaml")


NOTES = {
    "notes/files.yaml": "files:\n  - path: a.md\n    tags: [x]\n  - path: b.md\n",
    "notes/archive/files.yaml": "files:\n  - path: c.md\n",
    "notes/a.md": "検索 1\n検索 2\n検索 3\n他\n",
    "notes/b.md": "検索 1\n他\n",
    "notes/archive/c.md": "検索 1\n検索 2\n他\n",
}

PART_NOTES = {
    "notes/files.yaml": "files:\n  - path: a.md\n",
    "notes/a.md": "\n".join(
        [
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
    )
    + "\n",
}


def test_search_docs(make_env: Callable[..., SearchEnv]) -> None:
    """作業中の配信元の一覧（正常系）。"""
    # 準備
    env = make_env(TWO_DOCS)
    # 実行
    result = env.search()
    # 検証
    assert result.total_count == 2
    assert [item.id for item in result.items] == ["doc-1", "doc-2"]
    assert list(result.items[0].values) == list(SUMMARY_FIELDS)


def test_search_docs_when_full_and_seen(make_env: Callable[..., SearchEnv]) -> None:
    """本文と返し済み（正常系）。"""
    # 準備
    env = make_env(TWO_DOCS)
    condition = Condition(field="id", op="eq", values=["doc-1"])
    body = TWO_DOCS["docs/doc-1.yaml"]
    # 実行
    first = env.search(filter=condition, view="full", session_id="s1")
    second = env.search(filter=condition, view="full", session_id="s1")
    third = env.search(filter=condition, view="full", session_id="s1", repeat_seen=True)
    # 検証
    assert first.items[0].values["body"] == body
    assert first.items[0].scope == "full"
    assert second.items[0].values["body"] == SEEN_MARK
    assert second.items[0].path is None
    assert second.items[0].scope is None
    assert third.items[0].values["body"] == body
    assert third.items[0].scope == "full"


def test_search_docs_when_count_grouped(make_env: Callable[..., SearchEnv]) -> None:
    """件数と集計（正常系）。"""
    # 準備
    env = make_env(
        {
            "docs/doc-1.yaml": "id: doc-1\nname: 1\ntags: [a, b]\n",
            "docs/doc-2.yaml": "id: doc-2\nname: 2\ntags: [a]\n",
            "docs/doc-3.yaml": "id: doc-3\nname: 3\n",
        }
    )
    # 実行
    result = env.search(view="count", group_by="tags")
    # 検証
    assert result.items == []
    assert result.groups == [
        GroupCount(value="a", count=2),
        GroupCount(value="b", count=1),
        GroupCount(value="（なし）", count=1),
    ]


def test_search_docs_when_grouped_normalized(make_env: Callable[..., SearchEnv]) -> None:
    """表記だけが違う値をまとめる（正常系）。"""
    # 準備
    env = make_env(
        {
            "docs/doc-1.yaml": "id: doc-1\nname: 1\ntags: [mcp]\n",
            "docs/doc-2.yaml": "id: doc-2\nname: 2\ntags: [MCP, mcp, 設計]\n",
            "docs/doc-3.yaml": "id: doc-3\nname: 3\ntags: [ｍｃｐ]\n",
        }
    )
    # 実行
    result = env.search(view="count", group_by="tags")
    # 検証
    assert result.groups == [
        GroupCount(value="mcp", count=3),
        GroupCount(value="設計", count=1),
    ]


def test_search_docs_when_grouped_tie(make_env: Callable[..., SearchEnv]) -> None:
    """表記の文書の数が同じ（正常系）。"""
    # 準備
    env = make_env(
        {
            "docs/doc-1.yaml": "id: doc-1\nname: 1\nstatus: Draft\n",
            "docs/doc-2.yaml": "id: doc-2\nname: 2\nstatus: draft\n",
        }
    )
    # 実行
    result = env.search(view="count", group_by="status")
    # 検証
    assert result.groups == [GroupCount(value="Draft", count=2)]


def test_search_docs_when_limited(make_env: Callable[..., SearchEnv]) -> None:
    """上限と打ち切りと続き（正常系）。"""
    # 準備
    files = {
        f"docs/doc-{number}.yaml": f"id: doc-{number}\nname: n\ntext: {'x' * 9000}\n"
        for number in range(1, 6)
    }
    env = make_env(files)
    request = {"view": "full", "limit": 150, "max_chars": 20000}
    # 実行
    first = env.search(**request)
    second = env.search(**request, cursor=first.next_cursor)
    # 検証
    assert any("100" in note for note in first.notes)
    assert first.returned == 2
    assert first.truncated is True
    assert first.next_cursor is not None
    assert [item.id for item in second.items] == ["doc-3", "doc-4"]


def test_search_docs_when_order_by_dates(make_env: Callable[..., SearchEnv]) -> None:
    """日時の空は末尾（正常系）。"""
    # 準備
    env = make_env(
        {
            "docs/doc-1.yaml": "id: doc-1\nname: 1\nupdated: 2026-10-01T00:00:00+00:00\n",
            "docs/doc-2.yaml": "id: doc-2\nname: 2\n",
            "docs/doc-3.yaml": "id: doc-3\nname: 3\nupdated: 2026-10-05T00:00:00+00:00\n",
        }
    )
    # 実行
    result = env.search(order_by=[OrderKey(field="updated", direction="desc")])
    # 検証
    assert [item.id for item in result.items] == ["doc-3", "doc-1", "doc-2"]


def test_search_docs_when_snippets_regex(make_env: Callable[..., SearchEnv]) -> None:
    """正規表現で当てた文書の抜粋（正常系）。"""
    # 準備
    env = make_env({"docs/doc-1.yaml": "id: doc-1\n# TODO x\nname: 文書 1\n"})
    condition = Condition(field="body", op="regex", values=["^#\\s*TODO"])
    # 実行
    result = env.search(filter=condition, view="full", snippets=Snippets(before=0, after=0))
    # 検証
    assert result.items[0].snippets == [
        Snippet(lines=[SnippetLine(line=2, text="# TODO x", hit=True)])
    ]


def test_search_docs_when_id_values(make_env: Callable[..., SearchEnv]) -> None:
    """`order_by` なしで `id` の `eq` で絞ると、`values` の順に返す（正常系）。"""
    # 準備
    env = make_env(TWO_DOCS)
    condition = Condition(field="id", op="eq", values=["doc-2", "doc-1"])
    # 実行
    result = env.search(filter=condition)
    # 検証
    assert [item.id for item in result.items] == ["doc-2", "doc-1"]


def test_search_docs_when_id_values_and_order_by(make_env: Callable[..., SearchEnv]) -> None:
    """`order_by` を明示した `id` の `eq` は、`id` の昇順で返す（正常系）。"""
    # 準備
    env = make_env(TWO_DOCS)
    condition = Condition(field="id", op="eq", values=["doc-2", "doc-1"])
    # 実行
    result = env.search(filter=condition, order_by=[OrderKey(field="id")])
    # 検証
    assert [item.id for item in result.items] == ["doc-1", "doc-2"]


def test_search_docs_when_ordered_by_matches(make_env: Callable[..., SearchEnv]) -> None:
    """当たった数で並べる（正常系）。"""
    # 準備
    env = make_env(NOTES, documents=[_notes_table()])
    body_condition = Condition(field="body", op="contains", values=["検索"])
    archive = Group.model_validate(
        {"not": {"field": "@path", "op": "glob", "values": ["notes/archive/**"]}}
    )
    node = Group.model_validate({"and": [body_condition, archive]})
    # 実行
    ordered = env.search(
        filter=node,
        fields=["@matches"],
        order_by=[OrderKey(field="@matches", direction="desc")],
    )
    without_matches = env.search(filter=node)
    # 検証
    assert [(item.id, item.values["@matches"]) for item in ordered.items] == [
        ("notes/a.md", 3),
        ("notes/b.md", 1),
    ]
    assert all("@matches" not in item.values for item in without_matches.items)


def test_search_docs_when_matches_under_not(make_env: Callable[..., SearchEnv]) -> None:
    """`not` の下の本文の条件は数えない（正常系）。"""
    # 準備
    env = make_env(NOTES, documents=[_notes_table()])
    node = Group.model_validate(
        {
            "not": {
                "and": [
                    {"field": "body", "op": "contains", "values": ["検索"]},
                    {"field": "tags", "op": "eq", "values": ["x"]},
                ]
            }
        }
    )
    # 実行
    result = env.search(filter=node, fields=["@matches"])
    # 検証
    assert [(item.id, item.values["@matches"]) for item in result.items] == [
        ("notes/archive/c.md", 0),
        ("notes/b.md", 0),
    ]


def test_search_docs_when_part_of_body(make_env: Callable[..., SearchEnv]) -> None:
    """本文の一部と返し済み（正常系）。"""
    # 準備
    env = make_env(PART_NOTES, documents=[_notes_table()])
    condition = Condition(field="id", op="eq", values=["notes/a.md"])
    request = {"filter": condition, "view": "full", "session_id": "s1"}
    # 実行
    by_section = env.search(**request, sections=["決まったこと"])
    by_lines = env.search(**request, lines=LineRange(offset=3, limit=2))
    whole = env.search(**request)
    again = env.search(**request, sections=["決まったこと"])
    # 検証
    section_item = by_section.items[0]
    assert section_item.values["body"] == "## 決まったこと\n7 行目 検索\n詳細"
    assert section_item.scope == "section"
    assert section_item.ranges == [BodyRange(6, 8)]
    assert section_item.total_lines == 10
    assert by_lines.items[0].values["body"] == "## 経緯\n経緯の本文"
    assert by_lines.items[0].ranges == [BodyRange(3, 4)]
    whole_item = whole.items[0]
    assert whole_item.values["body"] == PART_NOTES["notes/a.md"]
    assert whole_item.scope == "full"
    assert whole_item.ranges is None
    assert whole_item.total_lines is None
    assert again.items[0].values["body"] == section_item.values["body"]


def test_search_docs_when_part_of_body_with_snippets(make_env: Callable[..., SearchEnv]) -> None:
    """切り出した範囲の抜粋と当たる見出しの無い文書（正常系）。"""
    # 準備
    files = {**PART_NOTES, "docs/doc-1.yaml": "id: doc-1\nname: 文書 1\n"}
    env = make_env(files, documents=[_notes_table(), _yaml_table()])
    snippet_condition = Condition(field="body", op="contains", values=["検索"])
    # 実行
    snippeted = env.search(
        filter=snippet_condition,
        view="full",
        sections=["決まったこと"],
        snippets=Snippets(context_lines=0),
    )
    missing = env.search(
        filter=Group.model_validate(
            {
                "or": [
                    {"field": "id", "op": "eq", "values": ["notes/a.md"]},
                    {"field": "id", "op": "eq", "values": ["doc-1"]},
                ]
            }
        ),
        view="full",
        sections=["無い見出し"],
    )
    # 検証
    assert snippeted.items[0].snippets == [
        Snippet(lines=[SnippetLine(line=7, text="7 行目 検索", hit=True)])
    ]
    assert [(item.id, item.values["body"], item.ranges) for item in missing.items] == [
        ("doc-1", "", []),
        ("notes/a.md", "", []),
    ]
    assert len(missing.notes) == 2
    assert any("doc-1" in note and "YAML" in note for note in missing.notes)
    assert any("notes/a.md" in note and "無い見出し" in note for note in missing.notes)


def test_search_docs_when_unreadable_file(make_env: Callable[..., SearchEnv]) -> None:
    """読めないファイル（正常系）。"""
    # 準備
    env = make_env({**TWO_DOCS, "docs/broken.yaml": "a: [1\n"})
    # 実行
    result = env.search()
    # 検証
    assert [item.id for item in result.items] == ["doc-1", "doc-2"]
    assert any("docs/broken.yaml" in note for note in result.notes)


def test_search_docs_when_read_validator(make_env: Callable[..., SearchEnv]) -> None:
    """読み取りの検査の警告（正常系）。"""
    # 準備
    code = "import json; print(json.dumps([{'path': 'x', 'rule': 'bad'}]))"
    validators = [ScriptEntry(id="v", run=[sys.executable, "-c", code], on=["read"])]
    env = make_env(TWO_DOCS, validators=validators, row_validators=["v"])
    # 実行
    result = env.search()
    # 検証
    assert result.total_count == 2
    assert any("bad" in note for note in result.notes)


def test_search_docs_when_unknown_field(make_env: Callable[..., SearchEnv]) -> None:
    """知らない項目（異常系）。"""
    # 準備
    env = make_env(TWO_DOCS)
    condition = Condition(field="nmae", op="eq", values=["x"])
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        env.search(filter=condition)
    assert exc_info.value.violations[0].path == "filter.field"
    assert "name" in exc_info.value.violations[0].fix


def test_search_when_records_fields(make_env: Callable[..., SearchEnv]) -> None:
    """records の行の要素の項目で絞り込む（正常系）。"""
    # 準備
    table = DocumentTable(
        id="notes",
        paths=["notes/files.yaml"],
        schema_path="schemas/files.schema.yaml",
        records="files",
        body_file="path",
    )
    files_schema = load_yaml(records_files_schema("owner", "string"))
    env = make_env(
        {
            "notes/files.yaml": (
                "files:\n  - path: a.md\n    owner: alice\n  - path: b.md\n    owner: bob\n"
            ),
            "notes/a.md": "# a\n",
            "notes/b.md": "# b\n",
        },
        documents=[table],
        schemas={"notes": files_schema},
    )
    condition = Condition(field="owner", op="eq", values=["alice"])
    # 実行
    result = env.search(filter=condition)
    # 検証
    assert result.total_count == 1
    assert [item.id for item in result.items] == ["notes/a.md"]
    assert result.notes == []


def test_search_docs_when_sources_all(
    tmp_path: Path,
    make_env: Callable[..., SearchEnv],
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
) -> None:
    """全ての配信元（正常系）。"""
    # 準備
    table = DocumentTable(id="rules", paths=["docs/*.yaml"], schema_path="schemas/rule.schema.yaml")
    config = make_source_config(documents=[table])
    sample_root = tmp_path / "sample"
    notes_root = tmp_path / "notes"
    other_root = tmp_path / "other"
    write_files(notes_root, {"docs/note-1.yaml": "id: note-1\nname: メモ\n"})
    write_files(other_root, {"docs/other-1.yaml": "id: other-1\nname: 他\n"})
    notes = make_served_source(
        id="notes", root=notes_root, config=config, scope_read=[str(sample_root)], scope_write=[]
    )
    other = make_served_source(
        id="other", root=other_root, config=config, scope_read=["/zzz"], scope_write=[]
    )
    env = make_env(TWO_DOCS, extra_sources=[notes, other])
    # 実行
    result = env.search(source="*")
    # 検証
    assert result.per_source == {"sample": 2, "notes": 1}
    assert {item.source for item in result.items} == {"sample", "notes"}


def test_search_docs_when_location(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """文書の場所と範囲（正常系）。"""
    # 準備
    root = git_repo(
        {
            "docs/doc-1.yaml": "id: doc-1\nname: 文書 1\ndescription: 1 件目\n",
            "data/list.yaml": "items:\n  - id: item-1\n    name: 項目 1\n",
        }
    )
    documents = [
        DocumentTable(id="rules", paths=["docs/*.yaml"], schema_path="schemas/rule.schema.yaml"),
        DocumentTable(
            id="items",
            paths=["data/list.yaml"],
            schema_path="schemas/rule.schema.yaml",
            records="items",
        ),
    ]
    source = make_served_source(
        id="sample",
        root=root,
        config=make_source_config(documents=documents),
        is_git=True,
        repo_root=root,
    )
    store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
    env = SearchEnv(
        make_registry(source),
        store,
        DocumentChecker(store, timeout_sec=10),
        SeenStore(tmp_path / "seen.sqlite3", retention_days=7),
        root,
    )
    doc_1 = Condition(field="id", op="eq", values=["doc-1"])
    # 実行
    full = env.search(view="full")
    cut = env.search(filter=doc_1, view="full", max_chars_per_field=10)
    snippets = env.search(
        filter=Condition(field="body", op="contains", values=["文書"]),
        view="full",
        snippets=Snippets(context_lines=1, max_per_doc=3),
    )
    summary = env.search(filter=doc_1, view="summary")
    ids = env.search(filter=doc_1, view="ids")
    revision = env.search(filter=doc_1, view="full", ref="HEAD")
    # 検証
    assert [(item.id, item.path, item.scope) for item in full.items] == [
        ("doc-1", str(root / "docs" / "doc-1.yaml"), "full"),
        ("item-1", str(root / "data" / "list.yaml"), "section"),
    ]
    assert [(item.path, item.scope) for item in cut.items] == [
        (str(root / "docs" / "doc-1.yaml"), "section")
    ]
    assert [(item.path, item.scope) for item in snippets.items] == [
        (str(root / "docs" / "doc-1.yaml"), "section")
    ]
    assert [(item.path, item.scope) for item in summary.items] == [
        (str(root / "docs" / "doc-1.yaml"), "summary")
    ]
    assert [(item.path, item.scope) for item in ids.items] == [(None, None)]
    assert [(item.path, item.scope) for item in revision.items] == [(None, None)]


TERM_DOCS = {
    "terms/scope.yaml": (
        "id: scope\nname: 作業範囲\ndescription: 触ってよい範囲\naliases: [scope, 担当範囲]\n"
    ),
    "terms/other.yaml": "id: other\nname: 別の用語\ndescription: 当たらない用語\n",
}


def _terms_table() -> DocumentTable:
    """`alias_type: term` の文書の行を返す。"""
    return DocumentTable(
        id="terms",
        paths=["terms/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        alias_type="term",
    )


def test_search_docs_when_term(make_env: Callable[..., SearchEnv]) -> None:
    """用語で引く（正常系）。"""
    # 準備
    env = make_env(TERM_DOCS, documents=[_terms_table()])
    # 実行
    results = [
        env.search(source="sample", term="担当範囲", view="ids"),
        env.search(source="sample", term="SCOPE", view="ids"),
        env.search(source="sample", term="担当", view="ids"),
    ]
    plain_env = make_env(TWO_DOCS, documents=[_yaml_table()])
    plain = plain_env.search(source="sample", term="担当範囲", view="ids")
    # 検証
    assert [[item.id for item in result.items] for result in results] == [["scope"], ["scope"], []]
    assert plain.items == []
    assert any("alias_type を持つ documents の行が無い" in note for note in plain.notes)

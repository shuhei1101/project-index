from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from project_index.features.documents.store import DocumentStore
from project_index.features.history.snapshot import SnapshotStore
from project_index.features.sources.service import load_source

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.documents.types import Document
    from project_index.features.settings.types import SourceEntry


MCP_FILTER = {"field": "tags", "op": "eq", "values": ["mcp"]}
NONE_FILTER = {"field": "tags", "op": "eq", "values": ["none"]}
TODAY = date(2026, 10, 31)


def _tagged_documents(make_document: Callable[..., Document]) -> list[Document]:
    """`tags: [mcp]` の文書を rules と notes に 1 件ずつ、タグの無い文書を rules に 1 件作る。"""
    return [
        make_document(
            id="rule-mcp",
            kind="rules",
            path="docs/rule/mcp.yaml",
            data={"tags": ["mcp"]},
            metadata={"tags": ["mcp"]},
        ),
        make_document(id="rule-plain", kind="rules", path="docs/rule/plain.yaml"),
        make_document(
            id="notes/mcp",
            kind="prompts",
            path="prompts/mcp.md",
            data={"tags": ["mcp"]},
            metadata={"tags": ["mcp"]},
        ),
    ]


def test_nav_auto_counts(make_document: Callable[..., Document]) -> None:
    """入れ子の auto を数える（正常系）。"""
    from project_index.features.read.nav import nav_auto_counts
    from project_index.features.search.fields import known_fields

    # 準備
    nav = {
        "tabs": [
            {"title": "mcp", "items": [{"auto": {"filter": MCP_FILTER}}]},
            {
                "title": "設計",
                "items": [{"group": "規約", "items": [{"auto": {"document": "rules"}}]}],
            },
            {"title": "none", "items": [{"auto": {"filter": NONE_FILTER}}]},
        ]
    }
    # 実行
    result = nav_auto_counts(
        nav, _tagged_documents(make_document), fields=known_fields([]), today=TODAY
    )
    # 検証
    assert [(count.path, count.tab, count.count) for count in result] == [
        ("nav.tabs[0].items[0].auto", "mcp", 2),
        ("nav.tabs[1].items[0].items[0].auto", "設計", 2),
        ("nav.tabs[2].items[0].auto", "none", 0),
    ]


def test_check_nav_filters() -> None:
    """知らない項目と無い行（異常系）。"""
    from project_index.features.read.nav import check_nav_filters
    from project_index.features.search.fields import known_fields

    # 準備
    nav = {
        "tabs": [
            {
                "title": "x",
                "items": [{"auto": {"filter": {"field": "nmae", "op": "eq", "values": ["x"]}}}],
            },
            {"title": "y", "items": [{"auto": {"document": "none"}}]},
        ]
    }
    # 実行
    result = check_nav_filters(nav, table_ids=["rules"], fields=known_fields([]))
    # 検証
    assert [item.path for item in result] == [
        "nav.tabs[0].items[0].auto.filter.field",
        "nav.tabs[1].items[0].auto.document",
    ]
    assert "name" in result[0].fix


def test_nav_warnings(
    make_alias_source_dir: Callable[..., Path],
    make_entry: Callable[..., SourceEntry],
    tmp_path: Path,
) -> None:
    """0 件の条件（正常系）。"""
    from project_index.features.read.nav import nav_warnings

    # 準備
    config = make_alias_source_dir(none_nav=True)
    source, _ = load_source(make_entry(str(config), source_id="sample"), index=0)
    assert source is not None
    store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
    # 実行
    result = nav_warnings(store, source, today=TODAY)
    # 検証
    assert [item.path for item in result] == ["nav.tabs[1].items[0].auto.filter"]
    assert result[0].rule.startswith("none:")


def test_nav_warnings_when_no_nav(
    make_alias_source_dir: Callable[..., Path],
    make_entry: Callable[..., SourceEntry],
    tmp_path: Path,
) -> None:
    """nav が無い（正常系）。"""
    from project_index.features.read.nav import nav_warnings

    # 準備
    config = make_alias_source_dir()
    source, _ = load_source(make_entry(str(config), source_id="sample"), index=0)
    assert source is not None
    store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
    # 実行
    result = nav_warnings(store, source, today=TODAY)
    # 検証
    assert result == []


OWNER_FILTER = {"field": "owner", "op": "eq", "values": ["alice"]}


def test_nav_warnings_when_records_filter(
    make_records_nav_source_dir: Callable[..., Path],
    make_entry: Callable[..., SourceEntry],
    tmp_path: Path,
) -> None:
    """records の行の 1 行の項目の条件を警告しない（正常系）。"""
    from project_index.features.read.nav import nav_warnings

    # 準備
    config = make_records_nav_source_dir("owner", "string", {"a": "alice"}, nav_filter=OWNER_FILTER)
    source, _ = load_source(make_entry(str(config), source_id="sample"), index=0)
    assert source is not None
    store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
    # 実行
    result = nav_warnings(store, source, today=TODAY)
    # 検証
    assert result == []

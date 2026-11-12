from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from project_index.features.documents.store import DocumentStore
from project_index.features.history.snapshot import SnapshotStore
from project_index.features.read import nav as nav_module
from project_index.features.read.types import NavItem
from project_index.features.sources.service import load_source
from project_index.features.sources.types import DocumentTable

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.documents.types import Document
    from project_index.features.settings.types import SourceEntry


def _tables() -> list[DocumentTable]:
    """文書の行を返す。"""
    return [
        DocumentTable(
            id="rules",
            paths=["docs/rule/*.yaml"],
            schema_path="schemas/rule.schema.yaml",
            title="規約",
        ),
        DocumentTable(
            id="architecture",
            paths=["docs/design/architecture.yaml"],
            schema_path="schemas/rule.schema.yaml",
        ),
        DocumentTable(
            id="prompts",
            paths=["prompts/files.yaml"],
            schema_path="schemas/rule.schema.yaml",
            records="files",
            body_file="path",
            title="プロンプト",
        ),
    ]


def _shape(item: NavItem) -> Any:
    """項目を、page はパス、group は（名前・子の並び）にして返す。"""
    if item.kind == "page":
        return item.path
    return (item.title, [_shape(child) for child in item.items])


def _folder_tables() -> list[DocumentTable]:
    """`paths: [rules/**/*.yaml]` の行 `rules` を返す。"""
    return [
        DocumentTable(id="rules", paths=["rules/**/*.yaml"], schema_path="schemas/rule.schema.yaml")
    ]


def _rule_documents(make_document: Callable[..., Document], paths: list[str]) -> list[Document]:
    """行 `rules` の文書を、ファイル名を ID にして作る。"""
    return [
        make_document(
            id=Path(path).stem if Path(path).stem != "index" else "lang-index",
            kind="rules",
            path=path,
        )
        for path in paths
    ]


def test_folder_items(make_document: Callable[..., Document]) -> None:
    """入れ子のフォルダと並び（正常系）。"""
    # 準備
    rows = {row.id: row for row in _folder_tables()}
    documents = _rule_documents(
        make_document,
        [
            "rules/z.yaml",
            "rules/a.yaml",
            "rules/lang/ts.yaml",
            "rules/lang/index.yaml",
            "rules/lang/py/style.yaml",
            "rules/b/x.yaml",
        ],
    )
    # 実行
    items = nav_module._folder_items(documents, rows=rows)
    # 検証
    assert [_shape(item) for item in items] == [
        "rules/a",
        "rules/z",
        ("b", ["rules/b/x"]),
        ("lang", ["rules/lang/index", "rules/lang/ts", ("py", ["rules/lang/py/style"])]),
    ]


def test_folder_items_when_multiple_globs(make_document: Callable[..., Document]) -> None:
    """先に並ぶ glob の起点を使う（正常系）。"""
    # 準備
    row = DocumentTable(
        id="docs",
        paths=["docs/guide/**/*.md", "docs/**/*.md"],
        schema_path="schemas/rule.schema.yaml",
    )
    documents = [make_document(id="a", kind="docs", path="docs/guide/start/a.md")]
    # 実行
    items = nav_module._folder_items(documents, rows={"docs": row})
    # 検証
    assert [_shape(item) for item in items] == [("start", ["docs/guide/start/a"])]


def test_folder_items_when_records(make_document: Callable[..., Document]) -> None:
    """管理用の YAML の行の文書は束ねない（正常系）。"""
    # 準備
    row = DocumentTable(
        id="notes",
        paths=["notes/index/files.yaml"],
        schema_path="schemas/files.schema.yaml",
        records="files",
        body_file="path",
    )
    documents = [
        make_document(id="b.md", kind="notes", path="notes/index/files.yaml", record_index=1),
        make_document(id="a.md", kind="notes", path="notes/index/files.yaml", record_index=0),
    ]
    # 実行
    items = nav_module._folder_items(documents, rows={"notes": row})
    # 検証
    assert all(item.kind == "page" for item in items)
    assert [item.path for item in items] == [
        "notes/index/files/a.md",
        "notes/index/files/b.md",
    ]


def _page_item(title: str, path: str, **overrides: Any) -> NavItem:
    """page の項目を作る。"""
    return NavItem(kind="page", title=title, path=path, **overrides)


def _group_item(title: str, items: list[NavItem]) -> NavItem:
    """group の項目を作る。"""
    return NavItem(kind="group", title=title, items=items)


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

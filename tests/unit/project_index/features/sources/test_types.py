from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from project_index.features.sources.types import DocumentTable, ServedSource, SourceConfig
from project_index.shared.errors import UnknownKindError

if TYPE_CHECKING:
    from collections.abc import Callable


def test_served_source_table(
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> None:
    """行を引く（正常系）。"""
    # 準備
    documents = [
        DocumentTable(
            id="rules", paths=["docs/rule/*.yaml"], schema_path="schemas/rule.schema.yaml"
        ),
        DocumentTable(id="notes", paths=["docs/note/*.md"], schema_path="schemas/rule.schema.yaml"),
    ]
    source = make_served_source(config=make_source_config(documents=documents))
    # 実行
    result = source.table("notes")
    # 検証
    assert result.id == "notes"


def test_served_source_table_when_unknown(
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> None:
    """無い種類（異常系）。"""
    # 準備
    documents = [
        DocumentTable(
            id="rules", paths=["docs/rule/*.yaml"], schema_path="schemas/rule.schema.yaml"
        ),
        DocumentTable(
            id="notes",
            paths=["docs/note/*.md"],
            schema_path="schemas/rule.schema.yaml",
            enabled=False,
        ),
    ]
    source = make_served_source(config=make_source_config(documents=documents))
    # 実行・検証
    with pytest.raises(UnknownKindError) as exc_info:
        source.table("x")
    assert exc_info.value.kinds == ["rules"]


def test_document_table_excludes() -> None:
    """ファイル名で当てる（正常系）。"""
    # 準備
    table = DocumentTable(
        id="rules",
        paths=["docs/**/*"],
        schema_path="schemas/rule.schema.yaml",
        exclude=["README.md", "_*.yaml"],
    )
    # 実行
    by_name = table.excludes("docs/a/README.md")
    by_glob = table.excludes("docs/_x.yaml")
    by_folder = table.excludes("docs/README.md/a.md")
    # 検証
    assert by_name is True
    assert by_glob is True
    assert by_folder is False


def test_document_table_matches() -> None:
    """paths に当たる（正常系）。"""
    # 準備
    table = DocumentTable(
        id="notes", paths=["docs/**/*.md"], schema_path="schemas/rule.schema.yaml", exclude=[]
    )
    # 実行
    result = table.matches("docs/a/b.md")
    # 検証
    assert result is True


def test_document_table_matches_when_excluded() -> None:
    """除外の名前に当たる（正常系）。"""
    # 準備
    table = DocumentTable(
        id="notes",
        paths=["docs/**/*.md"],
        schema_path="schemas/rule.schema.yaml",
        exclude=["README.md"],
    )
    # 実行
    excluded = table.matches("docs/a/README.md")
    kept = table.matches("docs/a/b.md")
    # 検証
    assert excluded is False
    assert kept is True


def test_document_table_matches_when_outside_paths() -> None:
    """paths に当たらない（正常系）。"""
    # 準備
    table = DocumentTable(id="notes", paths=["docs/*.md"], schema_path="schemas/rule.schema.yaml")
    # 実行
    result = table.matches("src/a.md")
    # 検証
    assert result is False

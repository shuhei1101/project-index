from __future__ import annotations

import pytest
from project_index.features.sources.types import DocumentTable
from project_index.features.write.placement import new_document_path
from project_index.shared.errors import InvalidArgumentError


def test_new_document_path() -> None:
    """glob から決める（正常系）。"""
    # 準備
    by_glob = DocumentTable(
        id="sample", paths=["docs/**/*.yaml"], schema_path="schemas/rule.schema.yaml"
    )
    by_records = DocumentTable(
        id="items",
        paths=["data/list.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="items",
    )
    # 実行
    glob_result = new_document_path(by_glob, "sample-doc")
    records_result = new_document_path(by_records, "item-1")
    # 検証
    assert glob_result == ("docs/sample-doc.yaml", False)
    assert records_result == ("data/list.yaml", True)


def test_new_document_path_when_excluded() -> None:
    """置き場所が除外の名前に当たる（異常系）。"""
    # 準備
    table = DocumentTable(
        id="sample",
        paths=["docs/rule/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        exclude=["index.yaml"],
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match=r"docs/rule/index\.yaml") as exc_info:
        new_document_path(table, "index")
    assert exc_info.value.violations[0].path == "kind"
    assert "docs/rule/index.yaml" in exc_info.value.violations[0].rule


def test_new_document_path_when_records_excluded() -> None:
    """records の行で管理用の YAML の名前が除外の名前に当たる（異常系）。"""
    # 準備
    table = DocumentTable(
        id="src",
        paths=["src/files.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="files",
        body_file="path",
        exclude=["files.yaml"],
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match=r"src/files\.yaml") as exc_info:
        new_document_path(table, "x")
    assert exc_info.value.violations[0].path == "kind"
    assert "src/files.yaml" in exc_info.value.violations[0].rule

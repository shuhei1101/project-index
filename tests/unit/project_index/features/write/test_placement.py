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
    """配置先が除外の名前に当たる（異常系）。"""
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


def test_new_document_path_when_records_glob() -> None:
    """records を持つ行で先頭が glob のため配置先を決められない（異常系）。"""
    # 準備
    table = DocumentTable(
        id="items",
        paths=["data/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="items",
    )
    # 実行・検証
    with pytest.raises(
        InvalidArgumentError, match="items の新しい文書の配置先を決められません"
    ) as exc_info:
        new_document_path(table, "item-1")
    assert exc_info.value.violations[0].path == "kind"
    assert (
        exc_info.value.violations[0].fix
        == "documents[].paths の先頭を glob を含まない 1 つのファイルにしてください"
    )


def test_new_document_path_when_no_glob() -> None:
    """records を持たない行で先頭が glob を含まないため配置先を決められない（異常系）。"""
    # 準備
    table = DocumentTable(
        id="sample", paths=["docs/list.yaml"], schema_path="schemas/rule.schema.yaml"
    )
    # 実行・検証
    with pytest.raises(
        InvalidArgumentError, match="sample の新しい文書の配置先を決められません"
    ) as exc_info:
        new_document_path(table, "sample-doc")
    assert exc_info.value.violations[0].path == "kind"
    assert exc_info.value.violations[0].fix == "documents[].paths の先頭を glob にしてください"


def test_new_document_path_when_filename_glob_remains() -> None:
    """records を持たない行で置き換えた後のファイル名に glob が残るため配置先を決められない（異常系）。"""
    # 準備
    table = DocumentTable(
        id="sample", paths=["docs/*-*.yaml"], schema_path="schemas/rule.schema.yaml"
    )
    # 実行・検証
    with pytest.raises(
        InvalidArgumentError, match="sample の新しい文書の配置先を決められません"
    ) as exc_info:
        new_document_path(table, "sample-doc")
    assert exc_info.value.violations[0].path == "kind"
    assert (
        exc_info.value.violations[0].fix
        == "documents[].paths の先頭のファイル名の glob を * の 1 つだけにしてください"
    )


def test_new_document_path_when_recursive_folder() -> None:
    """フォルダの階層が `**` だけで `paths` に当たる配置先は、ID がファイル名に入らなくても返却する（正常系）。"""
    # 準備
    table = DocumentTable(
        id="sample", paths=["docs/**/index.yaml"], schema_path="schemas/rule.schema.yaml"
    )
    # 実行
    result = new_document_path(table, "sample-doc")
    # 検証
    assert result == ("docs/index.yaml", False)


@pytest.mark.parametrize(
    "first",
    [
        pytest.param("docs/*/README.md", id="no-star-in-filename"),
        pytest.param("docs/*/*.yaml", id="star-in-filename"),
    ],
)
def test_new_document_path_when_outside_paths(first: str) -> None:
    """records を持たない行で決めたパスが paths に当たらないため配置先を決められない（異常系）。"""
    # 準備
    table = DocumentTable(id="sample", paths=[first], schema_path="schemas/rule.schema.yaml")
    # 実行・検証
    with pytest.raises(
        InvalidArgumentError, match="sample の新しい文書の配置先を決められません"
    ) as exc_info:
        new_document_path(table, "sample-doc")
    assert exc_info.value.violations[0].path == "kind"
    assert (
        exc_info.value.violations[0].fix
        == "documents[].paths の先頭のフォルダの階層の glob を ** にしてください"
    )

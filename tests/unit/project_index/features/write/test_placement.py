from __future__ import annotations

import pytest

from project_index.features.sources.types import DocumentTable
from project_index.features.write.placement import new_document_path, requested_document_path
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


def test_requested_document_path() -> None:
    """指定したパスを正規化して返却する（正常系）。"""
    # 準備
    table = DocumentTable(
        id="asset",
        paths=["chars/*/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        exclude=["chars/*/definition.yaml"],
    )
    # 実行
    result = requested_document_path(table, "chars/c1/./a1.yaml")
    # 検証
    assert result == "chars/c1/a1.yaml"


@pytest.mark.parametrize(
    "new_path",
    [
        pytest.param("other/a2.yaml", id="outside-paths"),
        pytest.param("chars/c1/definition.yaml", id="excluded"),
    ],
)
def test_requested_document_path_when_outside_paths(new_path: str) -> None:
    """paths に該当しない・exclude に該当するパスを断る（異常系）。"""
    # 準備
    table = DocumentTable(
        id="asset",
        paths=["chars/*/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        exclude=["chars/*/definition.yaml"],
    )
    # 実行・検証
    with pytest.raises(
        InvalidArgumentError, match="paths に該当しないか exclude に該当します"
    ) as exc_info:
        requested_document_path(table, new_path)
    assert exc_info.value.violations[0].path == "new_path"
    assert new_path in exc_info.value.violations[0].rule


@pytest.mark.parametrize(
    "new_path",
    [
        pytest.param("../outside/a2.yaml", id="parent"),
        pytest.param("chars/../../outside/a2.yaml", id="parent-after-normalize"),
        pytest.param("/tmp/a2.yaml", id="absolute"),
    ],
)
def test_requested_document_path_when_outside_source(new_path: str) -> None:
    """paths が ** で始まる行でも、配信元の外を指すパスを断る（異常系）。"""
    # 準備
    table = DocumentTable(id="any", paths=["**/*.yaml"], schema_path="schemas/rule.schema.yaml")
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="配信元の外を指します") as exc_info:
        requested_document_path(table, new_path)
    assert exc_info.value.violations[0].path == "new_path"
    assert exc_info.value.violations[0].fix == "配信元の直下からのパスを指定してください"


def test_requested_document_path_when_records() -> None:
    """records を持つ行は new_path を受けない（異常系）。"""
    # 準備
    table = DocumentTable(
        id="items",
        paths=["data/list.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="items",
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="records を持つため") as exc_info:
        requested_document_path(table, "data/list.yaml")
    assert exc_info.value.violations[0].path == "new_path"
    assert exc_info.value.violations[0].fix == "new_path を除いてください"

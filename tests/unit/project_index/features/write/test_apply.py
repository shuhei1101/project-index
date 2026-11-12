from __future__ import annotations

from typing import Any

import pytest
from project_index.features.sources.types import DocumentTable
from project_index.features.write import apply as apply_module
from project_index.features.write.apply import apply_operation
from project_index.features.write.types import Operation, TextEdit
from project_index.shared.errors import InvalidArgumentError


def _decisions_table(**overrides: Any) -> DocumentTable:
    """共通のキーと列名の対応を持つ文書の行を返す。"""
    values: dict[str, Any] = {
        "id": "decisions",
        "paths": ["decisions/*.yaml"],
        "schema_path": "schemas/decision.schema.yaml",
        "metadata": {"name": "title", "description": "meta.summary"},
    }
    values.update(overrides)
    return DocumentTable(**values)


def test_apply_operation() -> None:
    """部分更新の組み合わせ（正常系）。"""
    # 準備
    current = {"a": {"b": 1, "c": 2}, "tags": ["a", "b"], "d": "x"}
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        set={"a": {"b": 9}},
        unset=["d"],
        add_to={"tags": ["c"]},
        remove_from={"tags": ["a"]},
    )
    # 実行
    result = apply_operation(current, operation)
    # 検証
    assert result == {"a": {"b": 9, "c": 2}, "tags": ["b", "c"]}
    assert current == {"a": {"b": 1, "c": 2}, "tags": ["a", "b"], "d": "x"}


def test_apply_operation_when_text_edit_ambiguous() -> None:
    """一致が 2 か所（異常系）。"""
    # 準備
    current = {"description": "aXbXc"}
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        text_edits=[TextEdit(field="description", old="X", new="Y")],
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        apply_operation(current, operation)
    assert exc_info.value.violations[0].path == "text_edits[0].old"
    assert "2" in exc_info.value.violations[0].fix


def test_apply_operation_when_replace() -> None:
    """置き換え（正常系）。"""
    # 準備
    operation = Operation(op="replace", id="doc-1", expected_version="v1", data={"a": 3})
    # 実行
    result = apply_operation({"a": 1, "b": 2}, operation)
    # 検証
    assert result == {"a": 3}


def test_to_columns() -> None:
    """update の項目のパスを読み替える（正常系）。"""
    # 準備
    operation = Operation(
        op="update",
        id="d1",
        expected_version="v1",
        set={"name": "A", "tags": ["x"]},
        unset=["description"],
        text_edits=[TextEdit(field="name", old="a", new="b")],
    )
    # 実行
    result = apply_module.to_columns(operation, _decisions_table(), index=0)
    # 検証
    assert result.set == {"title": "A", "tags": ["x"]}
    assert result.unset == ["meta.summary"]
    assert result.text_edits[0].field == "title"
    assert operation.set == {"name": "A", "tags": ["x"]}


def test_to_columns_when_data() -> None:
    """create の data を列へ入れる（正常系）。"""
    # 準備
    operation = Operation(
        op="create",
        kind="decisions",
        data={"name": "A", "description": "d", "tags": ["x"]},
    )
    # 実行
    result = apply_module.to_columns(operation, _decisions_table(), index=0)
    # 検証
    assert result.data == {"title": "A", "meta": {"summary": "d"}, "tags": ["x"]}


@pytest.mark.parametrize(
    ("metadata", "values"),
    [
        pytest.param(
            {"name": "title", "description": "meta.summary"}, {"title": "A"}, id="column-name"
        ),
        pytest.param({}, {"name": "A"}, id="no-mapping"),
    ],
)
def test_to_columns_when_column_name(metadata: dict[str, str], values: dict[str, str]) -> None:
    """列名をそのまま渡す（正常系）。"""
    # 準備
    operation = Operation(op="update", id="d1", expected_version="v1", set=values)
    # 実行
    result = apply_module.to_columns(operation, _decisions_table(metadata=metadata), index=0)
    # 検証
    assert result.set == values


def test_to_columns_when_both() -> None:
    """共通のキーと列名を両方渡す（異常系）。"""
    # 準備
    operation = Operation(
        op="update", id="d1", expected_version="v1", set={"name": "a", "title": "b"}
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        apply_module.to_columns(operation, _decisions_table(), index=2)
    assert exc_info.value.violations[0].path == "operations[2].set.name"
    assert "title" in exc_info.value.violations[0].rule


def _tags_table(**overrides: Any) -> DocumentTable:
    """`tags` を全ての要素のキー、`main_tags` を選んだ要素のキーにした文書の行を返す。"""
    values: dict[str, Any] = {
        "id": "rules",
        "paths": ["docs/rule/*.yaml"],
        "schema_path": "schemas/rule.schema.yaml",
        "metadata": {"tags": "tags[].name", "main_tags": "tags[main].name"},
    }
    values.update(overrides)
    return DocumentTable(**values)


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        pytest.param(
            {"add_to": {"tags": ["c"]}},
            [{"name": "a", "main": True}, {"name": "b"}, {"name": "c"}],
            id="add-to",
        ),
        pytest.param({"remove_from": {"tags": ["b"]}}, [{"name": "a", "main": True}], id="remove"),
        pytest.param(
            {"set": {"tags": ["a", "c", "d"]}},
            [{"name": "a", "main": True}, {"name": "c"}, {"name": "d"}],
            id="set",
        ),
    ],
)
def test_expand_array_keys(change: dict[str, Any], expected: list[dict[str, Any]]) -> None:
    """全ての要素のキーの追加・削除・置き換え（正常系）。"""
    from project_index.features.write.apply import expand_array_keys

    # 準備
    current = {"tags": [{"name": "a", "main": True}, {"name": "b"}]}
    operation = Operation(op="update", id="r1", expected_version="v1", **change)
    # 実行
    result = expand_array_keys(operation, _tags_table(), current, index=0)
    # 検証
    assert result.set["tags"] == expected


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        pytest.param(
            {"set": {"main_tags": ["c"]}},
            [{"name": "a"}, {"name": "c", "main": True}, {"name": "d"}],
            id="set",
        ),
        pytest.param(
            {"add_to": {"main_tags": ["d"]}},
            [{"name": "a", "main": True}, {"name": "c"}, {"name": "d", "main": True}],
            id="add-to",
        ),
        pytest.param(
            {"remove_from": {"main_tags": ["a"]}},
            [{"name": "a"}, {"name": "c"}, {"name": "d"}],
            id="remove",
        ),
        pytest.param(
            {"unset": ["main_tags"]}, [{"name": "a"}, {"name": "c"}, {"name": "d"}], id="unset"
        ),
    ],
)
def test_expand_array_keys_when_main(
    change: dict[str, Any], expected: list[dict[str, Any]]
) -> None:
    """選んだ要素のキーの操作（正常系）。"""
    from project_index.features.write.apply import expand_array_keys

    # 準備
    current = {"tags": [{"name": "a", "main": True}, {"name": "c"}, {"name": "d"}]}
    operation = Operation(op="update", id="r1", expected_version="v1", **change)
    # 実行
    result = expand_array_keys(operation, _tags_table(), current, index=0)
    # 検証
    assert result.set["tags"] == expected


def test_expand_array_keys_when_create() -> None:
    """create の data（正常系）。"""
    from project_index.features.write.apply import expand_array_keys

    # 準備
    operation = Operation(
        op="create",
        kind="rules",
        data={"name": "r2", "tags": ["a", "b"], "main_tags": ["b"]},
    )
    # 実行
    result = expand_array_keys(operation, _tags_table(), None, index=0)
    # 検証
    assert result.data == {"name": "r2", "tags": [{"name": "a"}, {"name": "b", "main": True}]}


def test_expand_array_keys_when_unknown_name() -> None:
    """配列に無い名前（異常系）。"""
    from project_index.features.write.apply import expand_array_keys

    # 準備
    current = {"tags": [{"name": "a", "main": True}, {"name": "b"}]}
    operation = Operation(op="update", id="r1", expected_version="v1", set={"main_tags": ["z"]})
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="引数が正しくありません") as exc_info:
        expand_array_keys(operation, _tags_table(), current, index=1)
    assert exc_info.value.violations[0].path == "operations[1].set.main_tags"
    assert "z" in exc_info.value.violations[0].rule


def test_expand_array_keys_when_plain() -> None:
    """[] を使わない行（正常系）。"""
    from project_index.features.write.apply import expand_array_keys

    # 準備
    operation = Operation(op="update", id="r1", expected_version="v1", set={"tags": ["x"]})
    # 実行
    result = expand_array_keys(
        operation, _tags_table(metadata={"name": "title"}), {"tags": []}, index=0
    )
    # 検証
    assert result == operation


@pytest.mark.parametrize(
    ("operation", "expected_path"),
    [
        pytest.param(
            Operation(
                op="create",
                kind="rules",
                data={"name": "r2", "tags": [{"name": "a", "main": True}]},
            ),
            "operations[2].data.tags",
            id="create-data",
        ),
        pytest.param(
            Operation(
                op="update", id="r1", expected_version="v1", add_to={"tags": [{"name": "c"}]}
            ),
            "operations[2].add_to.tags",
            id="add-to",
        ),
        pytest.param(
            Operation(
                op="update",
                id="r1",
                expected_version="v1",
                remove_from={"main_tags": [{"name": "a"}]},
            ),
            "operations[2].remove_from.main_tags",
            id="remove-from-main",
        ),
    ],
)
def test_expand_array_keys_when_objects(operation: Operation, expected_path: str) -> None:
    """要素が文字列でない配列（異常系）。"""
    from project_index.features.write.apply import expand_array_keys

    # 準備
    current = (
        None if operation.op == "create" else {"tags": [{"name": "a", "main": True}, {"name": "b"}]}
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="引数が正しくありません") as exc_info:
        expand_array_keys(operation, _tags_table(), current, index=2)
    assert exc_info.value.violations[0].path == expected_path
    assert "名前（文字列）の配列" in exc_info.value.violations[0].rule


@pytest.mark.parametrize(
    ("change", "expected_path"),
    [
        pytest.param({"set": {"tags": "a"}}, "operations[0].set.tags", id="tags"),
        pytest.param({"set": {"main_tags": "a"}}, "operations[0].set.main_tags", id="main-tags"),
    ],
)
def test_expand_array_keys_when_string(change: dict[str, Any], expected_path: str) -> None:
    """配列でなく文字列 1 つ（異常系）。"""
    from project_index.features.write.apply import expand_array_keys

    # 準備
    current = {"tags": [{"name": "a", "main": True}, {"name": "b"}]}
    operation = Operation(op="update", id="r1", expected_version="v1", **change)
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="引数が正しくありません") as exc_info:
        expand_array_keys(operation, _tags_table(), current, index=0)
    assert exc_info.value.violations[0].path == expected_path

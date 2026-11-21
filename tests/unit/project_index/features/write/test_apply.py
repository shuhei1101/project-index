from __future__ import annotations

from typing import Any

import pytest

from project_index.features.sources.types import DocumentTable
from project_index.features.write import apply as apply_module
from project_index.features.write.apply import apply_body, apply_operation
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


def test_apply_operation_when_body() -> None:
    """@body を要素に当てない（正常系）。"""
    # 準備
    create = Operation(
        op="create", kind="notes", data={"id": "n2", "path": "n2.md", "@body": "本文"}
    )
    update = Operation(
        op="update",
        id="n1",
        expected_version="v1",
        set={"@body": "x"},
        text_edits=[TextEdit(field="@body", old="a", new="b")],
    )
    # 実行
    created = apply_operation(None, create)
    updated = apply_operation({"id": "n1", "path": "n1.md"}, update)
    # 検証
    assert created == {"id": "n2", "path": "n2.md"}
    assert updated == {"id": "n1", "path": "n1.md"}


@pytest.mark.parametrize(
    ("current_body", "operation", "expected"),
    [
        pytest.param(
            None,
            Operation(
                op="create", kind="notes", data={"id": "n2", "path": "n2.md", "@body": "本文"}
            ),
            "本文",
            id="create",
        ),
        pytest.param(
            "a\nb",
            Operation(op="update", id="n1", expected_version="v1", set={"@body": "x"}),
            "x",
            id="set",
        ),
        pytest.param(
            "a\nb",
            Operation(
                op="update",
                id="n1",
                expected_version="v1",
                text_edits=[TextEdit(field="@body", old="b", new="c")],
            ),
            "a\nc",
            id="text_edits",
        ),
        pytest.param(
            "a\nb",
            Operation(op="update", id="n1", expected_version="v1", set={"name": "y"}),
            None,
            id="no_body",
        ),
    ],
)
def test_apply_body(current_body: str | None, operation: Operation, expected: str | None) -> None:
    """create・set・text_edits の本文（正常系）。"""
    # 準備
    index = 0
    # 実行
    result = apply_body(current_body, operation, index=index)
    # 検証
    assert result == expected


def test_apply_body_when_text_edit_ambiguous() -> None:
    """本文の old が 2 か所に一致する（異常系）。"""
    # 準備
    operation = Operation(
        op="update",
        id="n1",
        expected_version="v1",
        text_edits=[TextEdit(field="@body", old="a", new="b")],
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        apply_body("a a", operation, index=1)
    assert exc_info.value.violations[0].path == "operations[1].text_edits[0].old"


@pytest.mark.parametrize(
    ("operation", "expected_path"),
    [
        pytest.param(
            Operation(op="update", id="n1", expected_version="v1", set={"@body": None}),
            "operations[0].set.@body",
            id="update_null",
        ),
        pytest.param(
            Operation(op="create", kind="notes", data={"id": "n2", "path": "n2.md", "@body": 123}),
            "operations[0].data.@body",
            id="create_number",
        ),
    ],
)
def test_apply_body_when_not_string(operation: Operation, expected_path: str) -> None:
    """文字列でない @body（異常系）。"""
    # 準備
    index = 0
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        apply_body("a", operation, index=index)
    assert [v.path for v in exc_info.value.violations] == [expected_path]


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


def _nested_table() -> DocumentTable:
    """`related` をどの深さの `refs` もまとめる列名にした文書の行を返す。"""
    return DocumentTable(
        id="nested",
        paths=["nested/*.yaml"],
        schema_path="schemas/nested.schema.yaml",
        metadata={"related": "**.refs[]"},
    )


@pytest.mark.parametrize(
    ("operation", "expected_path"),
    [
        pytest.param(
            Operation(op="update", id="n1", expected_version="v1", set={"related": []}),
            "operations[0].set.related",
            id="set",
        ),
        pytest.param(
            Operation(op="update", id="n1", expected_version="v1", unset=["related"]),
            "operations[0].unset",
            id="unset",
        ),
        pytest.param(
            Operation(op="create", kind="nested", data={"id": "n4", "related": []}),
            "operations[0].data.related",
            id="data",
        ),
        pytest.param(
            Operation(
                op="update",
                id="n1",
                expected_version="v1",
                text_edits=[TextEdit(field="related", old="a", new="b")],
            ),
            "operations[0].text_edits[0].field",
            id="text-edits",
        ),
    ],
)
def test_expand_array_keys_when_any_depth(operation: Operation, expected_path: str) -> None:
    """どの深さの列もまとめるキーへの操作（異常系）。"""
    from project_index.features.write.apply import expand_array_keys

    # 準備
    current: dict[str, Any] = {"id": "n1", "refs": [], "functions": [{"refs": []}]}
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="引数が正しくありません") as exc_info:
        expand_array_keys(operation, _nested_table(), current, index=0)
    assert exc_info.value.violations[0].path == expected_path
    assert "**.refs[]" in exc_info.value.violations[0].rule


def test_expand_array_keys_when_any_depth_column_name() -> None:
    """どの深さの列もまとめるキーの列名をそのまま渡す（正常系）。"""
    from project_index.features.write.apply import expand_array_keys

    # 準備
    current: dict[str, Any] = {"id": "n1", "refs": [], "functions": [{"refs": []}]}
    operation = Operation(op="update", id="n1", expected_version="v1", set={"refs": []})
    # 実行
    result = expand_array_keys(operation, _nested_table(), current, index=0)
    # 検証
    assert result == operation


_FUNCTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "functions": {
            "type": "array",
            "x-key": "name",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "process": {"type": "string"}},
            },
        },
    },
}


def test_apply_operation_when_text_edit_ref_path() -> None:
    """参照の型の項目のパスで配列の要素の中を置き換える（正常系）。"""
    # 準備
    current = {
        "functions": [
            {"name": "load", "process": "a書き出す"},
            {"name": "save", "process": "a書き出す"},
            {"name": "save", "process": "a書き出す"},
        ]
    }
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        text_edits=[TextEdit(field="#functions[save#2].process", old="書き出す", new="保存する")],
    )
    # 実行
    result = apply_operation(current, operation, schema=_FUNCTIONS_SCHEMA)
    # 検証
    assert result == {
        "functions": [
            {"name": "load", "process": "a書き出す"},
            {"name": "save", "process": "a書き出す"},
            {"name": "save", "process": "a保存する"},
        ]
    }


def test_apply_operation_when_text_edit_ref_path_unresolved() -> None:
    """参照の型の項目のパスが要素を指せない（異常系）。"""
    # 準備
    current = {"functions": [{"name": "load", "process": "a"}]}
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        text_edits=[TextEdit(field="#functions[missing].process", old="a", new="b")],
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="操作を適用できません") as exc_info:
        apply_operation(current, operation, schema=_FUNCTIONS_SCHEMA)
    violation = exc_info.value.violations[0]
    assert violation.path == "text_edits[0].field"
    _assert_field_fix(violation.fix)


def _assert_field_fix(fix: str) -> None:
    """`text_edits[{n}].field` の違反の `fix` が、項目のパスの指し方の 3 つの案内を持つことを確認する。"""
    # `x-key` の値で指す書き方
    assert "#functions[save].process" in fix
    # 位置で指す書き方
    assert "flows[35].expected[2]" in fix
    # 配列・オブジェクトそのものを書き換える操作
    assert "`set`・`add_to`・`remove_from`" in fix


def _functions_content() -> dict[str, Any]:
    """`x-key` の配列 `functions` が `load`・`save`・`save` の内容を返却する。"""
    return {
        "functions": [
            {"name": "load", "process": "a書き出す"},
            {"name": "save", "process": "a書き出す"},
            {"name": "save", "process": "a書き出す"},
        ]
    }


def test_apply_operation_when_text_edit_not_string() -> None:
    """文字列でない項目を指す（異常系）。"""
    # 準備
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        text_edits=[TextEdit(field="functions[save].process", old="書き出す", new="保存する")],
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="操作を適用できません") as exc_info:
        apply_operation(_functions_content(), operation, schema=_FUNCTIONS_SCHEMA)
    violation = exc_info.value.violations[0]
    assert violation.path == "text_edits[0].field"
    assert violation.rule == "文字列ではない項目は置き換えられません"
    _assert_field_fix(violation.fix)


def test_apply_operation_when_text_edit_path_invalid() -> None:
    """# で始まらない項目のパスの記載方法の誤り（異常系）。"""
    # 準備
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        text_edits=[TextEdit(field="functions[send-form].process", old="書き出す", new="保存する")],
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="操作を適用できません") as exc_info:
        apply_operation(_functions_content(), operation, schema=_FUNCTIONS_SCHEMA)
    violation = exc_info.value.violations[0]
    assert violation.path == "text_edits[0].field"
    assert "記載方法が誤っています" in violation.rule
    _assert_field_fix(violation.fix)


_MODELS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "models": {
            "type": "array",
            "x-key": "name",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "properties": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


def _models_content() -> dict[str, Any]:
    """`x-key` の配列 `models` を持つ内容を返す。"""
    return {
        "models": [
            {"name": "Row", "properties": ["a"]},
            {"name": "Col", "properties": ["b"]},
        ]
    }


def test_apply_operation_when_add_to_ref_path() -> None:
    """参照の型の項目のパスで要素の中の配列へ追加・削除する（正常系）。"""
    # 準備
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        add_to={"#models[Row].properties": ["c"]},
        remove_from={"#models[Row].properties": ["a"]},
    )
    # 実行
    result = apply_operation(_models_content(), operation, schema=_MODELS_SCHEMA)
    # 検証
    assert result == {
        "models": [
            {"name": "Row", "properties": ["c"]},
            {"name": "Col", "properties": ["b"]},
        ]
    }


_SET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "models": {
            "type": "array",
            "x-key": "name",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "label": {"type": "string"},
                    "kind": {"type": "string"},
                    "meta": {"type": "object"},
                },
            },
        },
        "notes": {"type": "object", "additionalProperties": {"type": "string"}},
    },
}


def _set_content() -> dict[str, Any]:
    """`#` で始まる `set` のキーのテストに使う内容を返す。"""
    return {
        "models": [
            {"name": "Row", "meta": {"x": 1}},
            {"name": "Col"},
        ],
        "notes": {"main": "a"},
    }


def test_apply_operation_when_set_ref_path() -> None:
    """`#` で始まる `set` のキーで要素へキーを追加・マージする（正常系）。"""
    # 準備
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        set={
            "#models[Col].label": "l",
            "#models[Row].meta": {"y": 2},
            "#notes[a.b]": "v",
        },
    )
    # 実行
    result = apply_operation(_set_content(), operation, schema=_SET_SCHEMA)
    # 検証
    assert result == {
        "models": [
            {"name": "Row", "meta": {"x": 1, "y": 2}},
            {"name": "Col", "label": "l"},
        ],
        "notes": {"main": "a", "a.b": "v"},
    }


def test_apply_operation_when_set_ref_path_element() -> None:
    """`#` で始まる `set` のキーで要素そのものへマージする（正常系）。"""
    # 準備
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        set={"#models[Col]": {"kind": "k"}},
    )
    # 実行
    result = apply_operation(_set_content(), operation, schema=_SET_SCHEMA)
    # 検証
    assert result["models"] == [
        {"name": "Row", "meta": {"x": 1}},
        {"name": "Col", "kind": "k"},
    ]


@pytest.mark.parametrize(
    ("key", "message"),
    [
        pytest.param("#models[Zzz].label", "name が Zzz の要素がありません", id="missing_element"),
        pytest.param("#models[Col].other.label", "にキー other がありません", id="missing_middle"),
        pytest.param(
            "models[Col].label",
            "`#` で始めて x-key の値で要素を指してください",
            id="selector",
        ),
    ],
)
def test_apply_operation_when_set_ref_path_unresolved(key: str, message: str) -> None:
    """`set` のキーを解けない（異常系）。"""
    # 準備
    current = _set_content()
    operation = Operation(op="update", id="doc-1", expected_version="v1", set={key: "n"})
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        apply_operation(current, operation, schema=_SET_SCHEMA)
    assert [violation.path for violation in exc_info.value.violations] == [f"set.{key}"]
    assert message in exc_info.value.violations[0].rule
    assert current == _set_content()


def test_apply_operation_when_add_to_selector_path() -> None:
    """`#` で始まらず要素の選び方を含むキー（異常系）。"""
    # 準備
    current = _models_content()
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        add_to={"models[Row].properties": ["d"]},
        remove_from={"models[Row].properties": ["a"]},
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        apply_operation(current, operation, schema=_MODELS_SCHEMA)
    assert [violation.path for violation in exc_info.value.violations] == [
        "add_to.models[Row].properties",
        "remove_from.models[Row].properties",
    ]
    assert current == _models_content()


def test_apply_operation_when_add_to_ref_path_unresolved() -> None:
    """参照の型の項目のパスを解けない・配列でない（異常系）。"""
    # 準備
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        add_to={"#models[Zzz].properties": ["d"]},
        remove_from={"#models[Row].name": ["d"]},
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        apply_operation(_models_content(), operation, schema=_MODELS_SCHEMA)
    assert [violation.path for violation in exc_info.value.violations] == [
        "add_to.#models[Zzz].properties",
        "remove_from.#models[Row].name",
    ]


def test_apply_operation_when_add_to_index_path() -> None:
    """位置で指すキーは今までどおり（正常系）。"""
    # 準備
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        add_to={"functions[0].refs": ["x"]},
    )
    # 実行
    result = apply_operation({"functions": [{"name": "f"}]}, operation)
    # 検証
    assert result == {"functions": [{"name": "f", "refs": ["x"]}]}


def test_apply_operation_when_unset_ref_path() -> None:
    """参照の型の項目のパスで要素の中の項目を削除する（正常系）。"""
    # 準備
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        unset=["#models[Col].properties"],
    )
    # 実行
    result = apply_operation(_models_content(), operation, schema=_MODELS_SCHEMA)
    # 検証
    assert result == {
        "models": [
            {"name": "Row", "properties": ["a"]},
            {"name": "Col"},
        ]
    }


def test_apply_operation_when_unset_unresolved() -> None:
    """`unset` の要素を解けない（異常系）。"""
    # 準備
    current = _models_content()
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        unset=["models[Row].properties", "#models[Zzz].properties"],
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        apply_operation(current, operation, schema=_MODELS_SCHEMA)
    assert [violation.path for violation in exc_info.value.violations] == [
        "unset.models[Row].properties",
        "unset.#models[Zzz].properties",
    ]
    assert current == _models_content()


_FLOWS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "flows": {
            "type": "array",
            "x-key": "name",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "summary": {"type": "string"}},
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
}


def _flows_content() -> dict[str, Any]:
    """`x-key` の配列 `flows` を持つ内容を返す。"""
    return {
        "flows": [
            {"name": "A", "summary": "s1"},
            {"name": "B", "summary": "s2"},
            {"name": "C", "summary": "s3"},
        ]
    }


def test_apply_operation_when_remove_from_x_key() -> None:
    """x-key の値と要素のオブジェクトで削除する（正常系）。"""
    # 準備
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        remove_from={"flows": ["B", {"name": "C", "summary": "s3"}, "B"]},
    )
    # 実行
    result = apply_operation(_flows_content(), operation, schema=_FLOWS_SCHEMA)
    # 検証
    assert result == {"flows": [{"name": "A", "summary": "s1"}]}


def test_apply_operation_when_remove_from_x_key_missing() -> None:
    """x-key を持つ配列に削除する要素が無い値（異常系）。"""
    # 準備
    current = _flows_content()
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        remove_from={"flows": ["A", "Z", {"name": "A", "summary": "x"}]},
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        apply_operation(current, operation, schema=_FLOWS_SCHEMA)
    violations = exc_info.value.violations
    assert [violation.path for violation in violations] == [
        "remove_from.flows",
        "remove_from.flows",
    ]
    assert "Z" in violations[0].rule
    assert "summary" in violations[1].rule
    assert "x" in violations[1].rule
    assert current == _flows_content()


def test_apply_operation_when_remove_from_without_x_key() -> None:
    """x-key を持たない配列は今までどおり（正常系）。"""
    # 準備
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        remove_from={"notes": ["b", "z"]},
    )
    # 実行
    result = apply_operation({"notes": ["a", "b"]}, operation, schema=_FLOWS_SCHEMA)
    # 検証
    assert result == {"notes": ["a"]}


def test_apply_operation_when_remove_then_add() -> None:
    """1 つの操作で削除してから追加する（正常系）。"""
    # 準備
    operation = Operation(
        op="update",
        id="doc-1",
        expected_version="v1",
        remove_from={"flows": ["A"], "notes": ["a"]},
        add_to={"flows": [{"name": "A", "summary": "s9"}], "notes": ["a"]},
    )
    # 実行
    result = apply_operation({**_flows_content(), "notes": ["a"]}, operation, schema=_FLOWS_SCHEMA)
    # 検証
    assert result == {
        "flows": [
            {"name": "B", "summary": "s2"},
            {"name": "C", "summary": "s3"},
            {"name": "A", "summary": "s9"},
        ],
        "notes": ["a"],
    }


def test_expand_array_keys_when_remove_then_add() -> None:
    """同じ名前を remove_from と add_to に渡す（正常系）。"""
    from project_index.features.write.apply import expand_array_keys

    # 準備
    current = {"tags": [{"name": "a", "main": True}, {"name": "b"}]}
    operation = Operation(
        op="update",
        id="r1",
        expected_version="v1",
        remove_from={"tags": ["b"], "main_tags": ["a"]},
        add_to={"tags": ["b"], "main_tags": ["a"]},
    )
    # 実行
    result = expand_array_keys(operation, _tags_table(), current, index=0)
    # 検証
    assert result.set["tags"] == [{"name": "a", "main": True}, {"name": "b"}]


def test_apply_operation_when_skipped() -> None:
    """何もしなかった unset・remove_from を集める（正常系）。"""
    from project_index.features.write.types import SkippedOperation

    # 準備
    current = {"notes": {"mcp/server.py の補足": "x"}, "labels": ["a"]}
    operation = Operation(
        op="update",
        id="d1",
        expected_version="v1",
        unset=["notes.mcp/server.py の補足", "notes.nonexistent"],
        remove_from={"labels": ["a", "z"], "missing": ["x"]},
    )
    skipped: list[SkippedOperation] = []
    # 実行
    result = apply_operation(current, operation, skipped=skipped)
    # 検証
    assert result == {"notes": {"mcp/server.py の補足": "x"}, "labels": []}
    assert skipped == [
        SkippedOperation(path="unset.notes.mcp/server.py の補足", reason="項目がありません"),
        SkippedOperation(path="unset.notes.nonexistent", reason="項目がありません"),
        SkippedOperation(path="remove_from.labels", reason="'z' の要素がありません"),
        SkippedOperation(path="remove_from.missing", reason="項目がありません"),
    ]


def test_expand_array_keys_when_remove_from_missing_name() -> None:
    """配列に無い名前の remove_from を集める（正常系）。"""
    from project_index.features.write.apply import expand_array_keys
    from project_index.features.write.types import SkippedOperation

    # 準備
    current = {"tags": [{"name": "a", "main": True}]}
    operation = Operation(
        op="update",
        id="r1",
        expected_version="v1",
        remove_from={"tags": ["z"], "main_tags": ["y"]},
    )
    skipped: list[SkippedOperation] = []
    # 実行
    result = expand_array_keys(operation, _tags_table(), current, index=0, skipped=skipped)
    # 検証
    assert result.set == {"tags": [{"name": "a", "main": True}]}
    assert skipped == [
        SkippedOperation(path="remove_from.tags", reason="'z' の要素がありません"),
        SkippedOperation(path="remove_from.main_tags", reason="'y' の要素がありません"),
    ]


def test_to_given_keys() -> None:
    """列名の項目のパスを指定したキーへ戻す（正常系）。"""
    from project_index.features.write.apply import to_given_keys
    from project_index.features.write.types import SkippedOperation

    # 準備
    given = Operation(op="update", id="d1", expected_version="v1", unset=["name", "other"])
    table = _decisions_table(metadata={"name": "title"})
    skipped = [
        SkippedOperation(path="unset.title", reason="項目がありません"),
        SkippedOperation(path="unset.other", reason="項目がありません"),
    ]
    # 実行
    result = to_given_keys(skipped, given, table)
    # 検証
    assert [item.path for item in result] == ["unset.name", "unset.other"]


def test_to_given_keys_when_array_column() -> None:
    """書き戻しが足した配列の列名を共通のキーへ戻す（正常系）。"""
    from project_index.features.write.apply import to_given_keys
    from project_index.features.write.types import SkippedOperation

    # 準備
    given = Operation(op="update", id="d1", expected_version="v1", unset=["labels"])
    table = _decisions_table(metadata={"labels": "items[].name"})
    skipped = [SkippedOperation(path="unset.items", reason="項目がありません")]
    # 実行
    result = to_given_keys(skipped, given, table)
    # 検証
    assert [item.path for item in result] == ["unset.labels"]

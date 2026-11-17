from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.documents import fields as fields_module
from project_index.features.documents.fields import (
    delete_field,
    get_field,
    parse_field_path,
    resolve_array,
    resolve_metadata,
    resolve_ref_path,
    set_field,
    set_field_at,
)
from project_index.features.sources.types import DocumentTable
from project_index.shared.errors import InvalidArgumentError

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.documents.types import Document


def test_parse_field_path() -> None:
    """キーと位置（正常系）。"""
    # 実行
    result = parse_field_path("a.b[0][1].c")
    # 検証
    assert result == ["a", "b", 0, 1, "c"]


@pytest.mark.parametrize(
    "path", [pytest.param("a..b", id="empty-key"), pytest.param("a[x-y]", id="bad-index")]
)
def test_parse_field_path_when_invalid(path: str) -> None:
    """空のキーと数字でない位置（異常系）。"""
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        parse_field_path(path)
    assert exc_info.value.violations[0].path == path


def test_parse_field_path_when_selector() -> None:
    """全ての要素と真偽値のキーで選ぶ要素（正常系）。"""
    from project_index.features.documents.fields import ArraySelector

    # 実行
    results = [parse_field_path("tags[].name"), parse_field_path("tags[main].name")]
    # 検証
    assert results == [
        ["tags", ArraySelector(key=None), "name"],
        ["tags", ArraySelector(key="main"), "name"],
    ]


def test_parse_field_path_when_any_depth() -> None:
    """先頭の `**`（正常系）。"""
    from project_index.features.documents.fields import AnyDepth, ArraySelector

    # 実行
    results = [parse_field_path("**.refs[]"), parse_field_path("**.a.b")]
    # 検証
    assert results == [
        [AnyDepth(), "refs", ArraySelector(key=None)],
        [AnyDepth(), "a", "b"],
    ]


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("a.**.b", id="not-head"),
        pytest.param("**", id="alone"),
        pytest.param("**.**.b", id="twice"),
    ],
)
def test_parse_field_path_when_any_depth_misplaced(path: str) -> None:
    """先頭でない `**`・`**` だけ・2 つの `**`（異常系）。"""
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="記載方法が誤っています") as exc_info:
        parse_field_path(path)
    assert exc_info.value.violations[0].path == path


def test_get_field() -> None:
    """入れ子と位置（正常系）。"""
    # 準備
    data = {"a": {"b": [{"c": 1}]}}
    # 実行
    result = get_field(data, "a.b[0].c")
    # 検証
    assert result == 1


@pytest.mark.parametrize("path", ["a.x", "a.b[3].c", "a.b.c"])
def test_get_field_when_missing(path: str) -> None:
    """たどれない（正常系）。"""
    # 準備
    data = {"a": {"b": [{"c": 1}]}}
    # 実行
    result = get_field(data, path)
    # 検証
    assert result is None


def test_get_field_when_selector() -> None:
    """要素を選んで取り出す（正常系）。"""
    # 準備
    data = {"tags": [{"name": "a", "main": True}, {"name": "b"}, "c"]}
    # 実行
    results = [
        get_field(data, "tags[].name"),
        get_field(data, "tags[main].name"),
        get_field({"tags": "x"}, "tags[].name"),
    ]
    # 検証
    assert results == [["a", "b"], ["a"], None]


@pytest.mark.parametrize(
    ("data", "path", "expected"),
    [
        pytest.param(
            {
                "refs": [{"to": "a"}],
                "functions": [{"name": "f", "refs": [{"to": "b"}]}, {"name": "g"}],
                "meta": {"refs": [{"to": "c"}]},
            },
            "**.refs[]",
            [{"to": "a"}, {"to": "b"}, {"to": "c"}],
            id="elements",
        ),
        pytest.param(
            {
                "refs": [{"to": "a"}],
                "functions": [{"name": "f", "refs": [{"to": "b"}]}, {"name": "g"}],
                "meta": {"refs": [{"to": "c"}]},
            },
            "**.refs[].to",
            ["a", "b", "c"],
            id="items",
        ),
        pytest.param({"a": 1}, "**.refs[]", None, id="missing"),
    ],
)
def test_get_field_when_any_depth(data: dict[str, Any], path: str, expected: object) -> None:
    """どの深さの同じ名前の列も集める（正常系）。"""
    # 実行
    result = get_field(data, path)
    # 検証
    assert result == expected


def test_set_field() -> None:
    """途中の辞書を作る（正常系）。"""
    # 準備
    data: dict[str, Any] = {}
    # 実行
    set_field(data, "a.b.c", 1)
    # 検証
    assert data == {"a": {"b": {"c": 1}}}


def test_set_field_when_append() -> None:
    """末尾へ追加（正常系）。"""
    # 準備
    data: dict[str, Any] = {"a": [1]}
    # 実行
    set_field(data, "a[1]", 2)
    # 検証
    assert data == {"a": [1, 2]}


def test_set_field_when_type_mismatch() -> None:
    """途中が文字列（異常系）。"""
    # 準備
    data: dict[str, Any] = {"a": "x"}
    # 実行・検証
    with pytest.raises(InvalidArgumentError):
        set_field(data, "a.b", 1)


def test_set_field_when_out_of_range() -> None:
    """飛んだ位置（異常系）。"""
    # 準備
    data: dict[str, Any] = {"a": [1]}
    # 実行・検証
    with pytest.raises(InvalidArgumentError):
        set_field(data, "a[3]", 2)


def test_set_field_when_selector() -> None:
    """要素の選び方を含むパス（異常系）。"""
    # 準備
    data: dict[str, Any] = {"tags": []}
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="を含む項目のパスには書き込めません"):
        set_field(data, "tags[].name", "a")


def test_set_field_when_any_depth() -> None:
    """どの深さでもを含むパス（異常系）。"""
    # 準備
    data: dict[str, Any] = {}
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="を含む項目のパスには書き込めません"):
        set_field(data, "**.refs", [])
    assert data == {}


def test_delete_field() -> None:
    """キーと位置（正常系）。"""
    # 準備
    data: dict[str, Any] = {"a": {"b": 1}, "c": [1, 2]}
    # 実行
    key_deleted = delete_field(data, "a.b")
    index_deleted = delete_field(data, "c[0]")
    # 検証
    assert key_deleted is True
    assert index_deleted is True
    assert data == {"a": {}, "c": [2]}


def test_delete_field_when_missing() -> None:
    """無い値（正常系）。"""
    # 準備
    data: dict[str, Any] = {}
    # 実行
    result = delete_field(data, "a.b")
    # 検証
    assert result is False
    assert data == {}


def test_delete_field_when_any_depth() -> None:
    """どの深さでもを含むパス（異常系）。"""
    # 準備
    data: dict[str, Any] = {"refs": []}
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="を含む項目のパスは削除できません"):
        delete_field(data, "**.refs")
    assert data == {"refs": []}


def test_resolve_metadata() -> None:
    """列名の対応と同じ名前の列（正常系）。"""
    # 準備
    table = DocumentTable(
        id="rules",
        paths=["docs/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        metadata={"name": "title"},
        alias_type="term",
    )
    data = {"id": "a", "title": "A", "tags": ["x"], "visibility": "internal"}
    # 実行
    result = resolve_metadata(data, table)
    # 検証
    assert result == {
        "id": "a",
        "name": "A",
        "tags": ["x"],
        "alias_type": "term",
        "visibility": "internal",
    }


def test_resolve_metadata_when_nested_field() -> None:
    """入れ子の列（正常系）。"""
    # 準備
    table = DocumentTable(
        id="rules",
        paths=["docs/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        metadata={"description": "meta.summary"},
    )
    data = {"meta": {"summary": "s"}}
    # 実行
    result = resolve_metadata(data, table)
    # 検証
    assert result["description"] == "s"


def test_resolve_metadata_when_any_depth() -> None:
    """最上位と入れ子の関連をまとめる（正常系）。"""
    # 準備
    table = DocumentTable(
        id="nested",
        paths=["nested/*.yaml"],
        schema_path="schemas/nested.schema.yaml",
        metadata={"related": "**.refs[]"},
    )
    n1 = {
        "id": "n1",
        "refs": [{"to": "n2", "type": "references"}],
        "functions": [{"refs": [{"to": "n3", "type": "references"}]}],
    }
    n2 = {"id": "n2"}
    # 実行
    results = [resolve_metadata(n1, table), resolve_metadata(n2, table)]
    # 検証
    assert results[0]["related"] == [
        {"to": "n2", "type": "references"},
        {"to": "n3", "type": "references"},
    ]
    assert "related" not in results[1]


def test_resolve_metadata_when_object_array() -> None:
    """オブジェクトの配列のタグ（正常系）。"""
    # 準備
    table = DocumentTable(
        id="rules",
        paths=["docs/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        metadata={"tags": "tags[].name", "main_tags": "tags[main].name"},
    )
    data = {"tags": [{"name": "mcp", "main": True}, {"name": "設計"}]}
    # 実行
    result = resolve_metadata(data, table)
    # 検証
    assert result["tags"] == ["mcp", "設計"]
    assert result["main_tags"] == ["mcp"]


def test_missing_ref_fields() -> None:
    """metadata に書いた列だけを数える（正常系）。"""
    # 準備
    table = DocumentTable(
        id="rules",
        paths=["docs/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        metadata={"name": "title", "description": "summary"},
    )
    data = {"summary": "s"}
    # 実行
    result = fields_module.missing_ref_fields(data, table)
    # 検証
    assert result == [("name", "title")]


@pytest.mark.parametrize(
    ("body_path", "expected"),
    [
        pytest.param("docs/a.md", True, id="markdown"),
        pytest.param("docs/B.MD", True, id="upper-case"),
        pytest.param("src/a.py", False, id="source-code"),
        pytest.param(None, False, id="no-body-file"),
    ],
)
def test_is_markdown_body(
    make_document: Callable[..., Document], body_path: str | None, expected: bool
) -> None:
    """本文のファイルの拡張子（正常系）。"""
    # 準備
    from project_index.features.documents.fields import is_markdown_body

    document = make_document(path="docs/x.md", body_path=body_path)
    # 実行
    result = is_markdown_body(document)
    # 検証
    assert result is expected


def test_unresolved_related() -> None:
    """source を持たない関連だけを照合する（正常系）。"""
    # 準備
    metadata = {
        "related": [
            {"to": "src/b.py"},
            {"to": "src/z.py"},
            {"to": "other-doc", "source": "other"},
            {"to": "src/y.py", "source": None},
            {"type": "tests"},
        ]
    }
    ids = {"src/a.py", "src/b.py"}
    # 実行
    result = fields_module.unresolved_related(metadata, ids)
    # 検証
    assert result == ["src/z.py", "src/y.py"]


def test_unresolved_related_when_not_list() -> None:
    """related が配列でない（正常系）。"""
    # 準備
    ids = {"src/a.py"}
    # 実行
    missing = fields_module.unresolved_related({"name": "a"}, ids)
    text = fields_module.unresolved_related({"related": "src/z.py"}, ids)
    # 検証
    assert missing == []
    assert text == []


def test_field_arrays() -> None:
    """最上位と入れ子の配列を元のまま返す（正常系）。"""
    from project_index.features.documents.fields import field_arrays

    # 準備
    data: dict[str, Any] = {"refs": [1], "functions": [{"refs": [2]}, {"name": "g"}]}
    # 実行
    nested = field_arrays(data, "**.refs[]")
    top = field_arrays(data, "refs")
    nested[1].clear()
    # 検証
    assert nested == [[1], []]
    assert data["functions"][0]["refs"] == []
    assert top == [[1]]


@pytest.mark.parametrize(
    ("data", "path"),
    [
        pytest.param({"refs": "x"}, "refs", id="not-list"),
        pytest.param({}, "**.refs[]", id="missing"),
    ],
)
def test_field_arrays_when_not_list(data: dict[str, Any], path: str) -> None:
    """配列でない・無い列（正常系）。"""
    from project_index.features.documents.fields import field_arrays

    # 実行
    result = field_arrays(data, path)
    # 検証
    assert result == []


_REF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "functions": {"$ref": "#/$defs/functions"},
        "steps": {"type": "array", "items": {"type": "object"}},
        "notes": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "$defs": {
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


def _ref_data() -> dict[str, Any]:
    """参照の型の項目のパスのテストに使う内容を返す。"""
    return {
        "functions": [
            {"name": "load", "process": "x"},
            {"name": "save", "process": "x"},
            {"name": "save", "process": "x"},
        ],
        "steps": [{"name": "a", "body": "x"}],
        "notes": {"main.py の補足": "x"},
    }


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("functions[save].process", ["functions", 1, "process"], id="first"),
        pytest.param("functions[save#2].process", ["functions", 2, "process"], id="second"),
    ],
)
def test_resolve_ref_path(path: str, expected: list[str | int]) -> None:
    """x-key の値と順番で要素を指す（正常系）。"""
    # 準備
    data = _ref_data()
    # 実行
    result = resolve_ref_path(data, _REF_SCHEMA, path)
    # 検証
    assert result == expected


def test_resolve_ref_path_when_dict_key() -> None:
    """`.` を含む辞書のキー（正常系）。"""
    # 準備
    data = {"notes": {"main.py の補足": "x"}}
    # 実行
    result = resolve_ref_path(data, _REF_SCHEMA, "notes[main.py の補足]")
    # 検証
    assert result == ["notes", "main.py の補足"]


@pytest.mark.parametrize(
    ("path", "message"),
    [
        pytest.param("steps[a].body", "x-key を持たない配列です", id="no_x_key"),
        pytest.param(
            "functions[missing].process", "name が missing の要素がありません", id="missing"
        ),
        pytest.param("functions[save#3].process", "name が save の要素は 2 個です", id="order"),
        pytest.param("notes[missing]", "キー missing がありません", id="no_key"),
    ],
)
def test_resolve_ref_path_when_unresolved(path: str, message: str) -> None:
    """要素・キーを指せない（異常系）。"""
    # 準備
    data = _ref_data()
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match=message):
        resolve_ref_path(data, _REF_SCHEMA, path)


def test_set_field_at() -> None:
    """`.` を含むキーへ書く（正常系）。"""
    # 準備
    data: dict[str, Any] = {"notes": {"main.py の補足": "x"}}
    # 実行
    set_field_at(data, ["notes", "main.py の補足"], "y")
    # 検証
    assert data == {"notes": {"main.py の補足": "y"}}


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


def _models_data() -> dict[str, Any]:
    """`x-key` の配列 `models` を持つ内容を返す。"""
    return {
        "models": [
            {"name": "Row", "properties": ["a"]},
            {"name": "Col", "properties": ["b"]},
        ]
    }


def test_resolve_array() -> None:
    """参照の型の項目のパスで要素の中の配列を返す（正常系）。"""
    # 準備
    data = _models_data()
    # 実行
    result = resolve_array(data, _MODELS_SCHEMA, "#models[Row].properties", create=True)
    # 検証
    assert result is data["models"][0]["properties"]


def test_resolve_array_when_plain_missing() -> None:
    """要素の選び方を含まないパスの項目が無い（正常系）。"""
    # 準備
    created: dict[str, Any] = {}
    untouched: dict[str, Any] = {}
    # 実行
    result_created = resolve_array(created, {}, "tags", create=True)
    result_untouched = resolve_array(untouched, {}, "tags", create=False)
    # 検証
    assert result_created == []
    assert created == {"tags": []}
    assert result_created is created["tags"]
    assert result_untouched is None
    assert untouched == {}


def test_resolve_array_when_index() -> None:
    """位置で指すパス（正常系）。"""
    # 準備
    data: dict[str, Any] = {"functions": [{"refs": ["x"]}]}
    # 実行
    result = resolve_array(data, {}, "functions[0].refs", create=True)
    # 検証
    assert result is data["functions"][0]["refs"]


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("models[Row].properties", id="key_selector"),
        pytest.param("models[].properties", id="all_selector"),
        pytest.param("**.properties", id="any_depth"),
    ],
)
def test_resolve_array_when_selector(path: str) -> None:
    """`#` で始まらず要素の選び方を含むパス（異常系）。"""
    # 準備
    data = _models_data()
    # 実行・検証
    with pytest.raises(InvalidArgumentError):
        resolve_array(data, _MODELS_SCHEMA, path, create=True)
    assert data == _models_data()


def test_resolve_array_when_unresolved() -> None:
    """参照の型の項目のパスを解けない（異常系）。"""
    # 準備
    data = _models_data()
    # 実行・検証
    with pytest.raises(InvalidArgumentError):
        resolve_array(data, _MODELS_SCHEMA, "#models[Zzz].properties", create=True)

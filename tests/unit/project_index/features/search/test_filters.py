from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest

from project_index.features.search.filters import (
    check_exclusion,
    check_filter,
    compile_regex,
    exclusion_of,
    is_excluded,
    match_filter,
    parse_compare_value,
)
from project_index.features.search.types import Condition, Group, LineRange, OrderKey, SearchRequest
from project_index.features.sources.types import DocumentTable

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.access.types import Target
    from project_index.features.documents.types import Document
    from project_index.features.sources.types import ServedSource, SourceConfig

TODAY = date(2026, 10, 28)
FIELDS = {
    "tags": "array",
    "name": "string",
    "updated": "date",
    "@path": "string",
    "@matches": "number",
}


def test_parse_compare_value() -> None:
    """日付の相対の値（正常系）。"""
    # 実行
    today = parse_compare_value("today", "date", today=TODAY)
    week_ago = parse_compare_value("-7d", "date", today=TODAY)
    absolute = parse_compare_value("2026-10-01", "date", today=TODAY)
    # 検証
    assert today == datetime(2026, 10, 28, tzinfo=UTC)
    assert week_ago == datetime(2026, 10, 21, tzinfo=UTC)
    assert absolute == datetime(2026, 10, 1, tzinfo=UTC)


def test_parse_compare_value_when_invalid() -> None:
    """読めない値（異常系）。"""
    # 実行・検証
    with pytest.raises(ValueError, match="number"):
        parse_compare_value("x", "number", today=TODAY)


def test_match_filter(make_document: Callable[..., Document]) -> None:
    """AND と OR の入れ子（正常系）。"""
    # 準備
    node = Group.model_validate(
        {
            "and": [
                {"field": "tags", "op": "eq", "values": ["mcp"]},
                {
                    "or": [
                        {"field": "name", "op": "contains", "values": ["ＭＣＰ"]},
                        {"field": "updated", "op": "gte", "values": ["-7d"]},
                    ]
                },
            ]
        }
    )
    matched = make_document(
        metadata={"tags": ["mcp"], "name": "mcp の決まり"},
        updated=datetime(2026, 10, 1, tzinfo=UTC),
    )
    other = make_document(
        metadata={"tags": ["x"], "name": "mcp の決まり"},
        updated=datetime(2026, 10, 27, tzinfo=UTC),
    )
    # 実行
    matched_result = match_filter(node, matched, fields=FIELDS, today=TODAY)
    other_result = match_filter(node, other, fields=FIELDS, today=TODAY)
    # 検証
    assert matched_result is True
    assert other_result is False


def test_match_filter_when_match_all(make_document: Callable[..., Document]) -> None:
    """複数の値の AND（正常系）。"""
    # 準備
    node = Condition(field="tags", op="eq", values=["a", "b"], match="all")
    both = make_document(metadata={"tags": ["a", "b", "c"]})
    only_a = make_document(metadata={"tags": ["a"]})
    # 実行
    both_result = match_filter(node, both, fields=FIELDS, today=TODAY)
    only_a_result = match_filter(node, only_a, fields=FIELDS, today=TODAY)
    # 検証
    assert both_result is True
    assert only_a_result is False


def test_match_filter_when_case_sensitive(make_document: Callable[..., Document]) -> None:
    """区別する（正常系）。"""
    # 準備
    node = Condition(field="name", op="eq", values=["Doc"], case_sensitive=True)
    document = make_document(metadata={"name": "doc"})
    # 実行
    result = match_filter(node, document, fields=FIELDS, today=TODAY)
    # 検証
    assert result is False


def test_match_filter_when_regex_lines(make_document: Callable[..., Document]) -> None:
    """正規表現は各行に当たる（正常系）。"""
    # 準備
    line_head = Condition(field="body", op="regex", values=["^## "])
    text_head = Condition(field="body", op="regex", values=["\\A## "])
    document = make_document(body="# x\n## y")
    # 実行
    line_head_result = match_filter(line_head, document, fields=FIELDS, today=TODAY)
    text_head_result = match_filter(text_head, document, fields=FIELDS, today=TODAY)
    # 検証
    assert line_head_result is True
    assert text_head_result is False


def test_match_filter_when_not(make_document: Callable[..., Document]) -> None:
    """束の否定と入れ子（正常系）。"""
    # 準備
    node = Group.model_validate(
        {
            "and": [
                {"field": "tags", "op": "eq", "values": ["a"]},
                {
                    "not": {
                        "or": [
                            {"field": "name", "op": "eq", "values": ["x"]},
                            {"field": "name", "op": "eq", "values": ["y"]},
                        ]
                    }
                },
            ]
        }
    )
    kept = make_document(metadata={"tags": ["a"], "name": "z"})
    excluded = make_document(metadata={"tags": ["a"], "name": "y"})
    # 実行
    kept_result = match_filter(node, kept, fields=FIELDS, today=TODAY)
    excluded_result = match_filter(node, excluded, fields=FIELDS, today=TODAY)
    # 検証
    assert kept_result is True
    assert excluded_result is False


def test_match_filter_when_glob(make_document: Callable[..., Document]) -> None:
    """パスの glob（正常系）。"""
    # 準備
    star = Condition(field="@path", op="glob", values=["notes/*.md"])
    upper = Condition(field="@path", op="glob", values=["NOTES/**"])
    direct = make_document(path="notes/a.md")
    nested = make_document(path="notes/archive/c.md")
    # 実行
    star_direct = match_filter(star, direct, fields=FIELDS, today=TODAY)
    star_nested = match_filter(star, nested, fields=FIELDS, today=TODAY)
    upper_direct = match_filter(upper, direct, fields=FIELDS, today=TODAY)
    upper_nested = match_filter(upper, nested, fields=FIELDS, today=TODAY)
    # 検証
    assert star_direct is True
    assert star_nested is False
    assert upper_direct is True
    assert upper_nested is True


def test_check_filter_when_group_keys() -> None:
    """束のキーが 2 つ（異常系）。"""
    # 準備
    node = Group.model_validate(
        {
            "and": [{"field": "name", "op": "eq", "values": ["a"]}],
            "not": {"field": "tags", "op": "eq", "values": ["x"]},
        }
    )
    request = SearchRequest(filter=node)
    # 実行
    violations = check_filter(request, FIELDS)
    # 検証
    assert [(violation.path, violation.rule) for violation in violations] == [
        ("filter", "and・or・not のどれか 1 つだけを持ってください")
    ]


def test_check_filter_when_not_child() -> None:
    """`not` の下の知らない項目（異常系）。"""
    # 準備
    node = Group.model_validate({"not": {"field": "nmae", "op": "eq", "values": ["x"]}})
    request = SearchRequest(filter=node)
    # 実行
    violations = check_filter(request, FIELDS)
    # 検証
    assert [violation.path for violation in violations] == ["filter.not.field"]


def test_check_filter_when_array_item_key_dotted() -> None:
    """配列の中のキーを `.` で指した項目の候補（異常系）。"""
    # 準備
    fields = {**FIELDS, "uses": "array", "uses[].id": "string"}
    request = SearchRequest(
        filter=Condition(field="uses.id", op="eq", values=["compare"]), group_by="uses.id"
    )
    # 実行
    violations = check_filter(request, fields)
    # 検証
    assert [(violation.path, violation.rule) for violation in violations] == [
        ("filter.field", "知らない項目です（uses.id）"),
        ("group_by", "知らない項目です（uses.id）"),
    ]
    assert all("uses[].id" in (violation.fix or "") for violation in violations)


def test_check_filter_when_matches() -> None:
    """`@matches` を条件に使う（異常系）。"""
    # 準備
    in_filter = SearchRequest(filter=Condition(field="@matches", op="gt", values=["1"]))
    in_order_by = SearchRequest(order_by=[OrderKey(field="@matches")])
    # 実行
    filter_violations = check_filter(in_filter, FIELDS)
    order_by_violations = check_filter(in_order_by, FIELDS)
    # 検証
    assert [violation.path for violation in filter_violations] == ["filter.field"]
    assert order_by_violations == []


def test_check_filter_when_body_range() -> None:
    """本文の範囲の引数の組み合わせ（異常系）。"""
    # 準備
    both = SearchRequest(view="full", sections=["a"], lines=LineRange(offset=1))
    not_full = SearchRequest(view="summary", sections=["a"])
    # 実行
    both_violations = check_filter(both, FIELDS)
    not_full_violations = check_filter(not_full, FIELDS)
    # 検証
    assert [(violation.path, violation.rule) for violation in both_violations] == [
        ("sections", "sections と lines は同時に指定できません")
    ]
    assert [(violation.path, violation.rule) for violation in not_full_violations] == [
        ("sections", "view: full のときだけ指定できます")
    ]


def test_compile_regex() -> None:
    """各行と大文字小文字（正常系）。"""
    # 準備
    text = "a\nb"
    # 実行
    insensitive = compile_regex("^b", case_sensitive=False).search(text)
    sensitive = compile_regex("^B", case_sensitive=True).search(text)
    # 検証
    assert insensitive is not None
    assert sensitive is None


def test_match_filter_when_columns(make_document: Callable[..., Document]) -> None:
    """行の metadata で対応付けた列で照合する（正常系）。"""
    # 準備
    node = Condition(field="category", op="eq", values=["使い方"])
    document = make_document(data={"section": "使い方"})
    # 実行
    with_columns = match_filter(
        node, document, fields=FIELDS, today=TODAY, columns={"category": "section"}
    )
    without_columns = match_filter(node, document, fields=FIELDS, today=TODAY)
    # 検証
    assert with_columns is True
    assert without_columns is False


EXCLUSION_FIELDS = {"status": "string", "name": "string", "@chars": "number"}


def test_check_exclusion() -> None:
    """共通のキーの条件（正常系）。"""
    # 準備
    value = {"field": "status", "op": "eq", "values": ["inactive"]}
    # 実行
    violations = check_exclusion(value, "documents[0].search_exclude", fields=EXCLUSION_FIELDS)
    # 検証
    assert violations == []


def test_check_exclusion_when_unknown_op() -> None:
    """比べ方の一覧に無い op（異常系）。"""
    # 準備
    value = {"field": "status", "op": "like", "values": ["inactive"]}
    # 実行
    violations = check_exclusion(value, "documents[0].search_exclude", fields=EXCLUSION_FIELDS)
    # 検証
    assert [violation.path for violation in violations] == ["documents[0].search_exclude.op"]


def test_check_exclusion_when_body() -> None:
    """比べられない項目（異常系）。"""
    # 準備
    body = {"field": "body", "op": "contains", "values": ["x"]}
    computed = {"and": [{"field": "@chars", "op": "gt", "values": ["1"]}]}
    # 実行
    body_violations = check_exclusion(body, "documents[0].search_exclude", fields=EXCLUSION_FIELDS)
    computed_violations = check_exclusion(
        computed, "documents[1].search_exclude", fields=EXCLUSION_FIELDS
    )
    # 検証
    assert [(violation.path, violation.rule) for violation in body_violations] == [
        (
            "documents[0].search_exclude.field",
            "既定の検索から除く条件に使用できない項目です（body）",
        )
    ]
    assert [violation.path for violation in computed_violations] == [
        "documents[1].search_exclude.and[0].field"
    ]


def test_exclusion_of() -> None:
    """条件の木と無い行（正常系）。"""
    # 準備
    with_condition = DocumentTable(
        id="assets",
        paths=["assets/*.yaml"],
        schema_path="schemas/asset.schema.yaml",
        search_exclude={"or": [{"field": "status", "op": "eq", "values": ["inactive"]}]},
    )
    without_condition = DocumentTable(
        id="rules", paths=["docs/*.yaml"], schema_path="schemas/rule.schema.yaml"
    )
    # 実行
    condition = exclusion_of(with_condition)
    nothing = exclusion_of(without_condition)
    # 検証
    assert isinstance(condition, Group)
    assert condition.any_of == [Condition(field="status", op="eq", values=["inactive"])]
    assert nothing is None


def test_is_excluded(make_document: Callable[..., Document]) -> None:
    """該当する文書・しない文書・条件なし（正常系）。"""
    # 準備
    condition = Condition(field="status", op="eq", values=["inactive"])
    inactive = make_document(metadata={"id": "a2", "status": "inactive"})
    active = make_document(metadata={"id": "a1", "status": "active"})
    # 実行
    inactive_result = is_excluded(inactive, condition, fields=EXCLUSION_FIELDS, today=TODAY)
    active_result = is_excluded(active, condition, fields=EXCLUSION_FIELDS, today=TODAY)
    no_condition = is_excluded(inactive, None, fields=EXCLUSION_FIELDS, today=TODAY)
    # 検証
    assert inactive_result is True
    assert active_result is False
    assert no_condition is False


def test_exclusion_flags(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
) -> None:
    """該当する文書だけ True（正常系）。"""
    from project_index.features.documents.store import DocumentStore
    from project_index.features.history.snapshot import SnapshotStore
    from project_index.features.search.filters import exclusion_flags

    # 準備
    root = tmp_path / "sample"
    write_files(
        root,
        {
            "schemas/rule.schema.yaml": "type: object\n",
            "assets/a1.yaml": "id: a1\nname: A1\nstatus: active\n",
            "assets/a2.yaml": "id: a2\nname: A2\nstatus: inactive\n",
            "docs/d1.yaml": "id: d1\nname: D1\nstatus: inactive\n",
        },
    )
    tables = [
        DocumentTable(
            id="assets",
            paths=["assets/*.yaml"],
            schema_path="schemas/rule.schema.yaml",
            search_exclude={"field": "status", "op": "eq", "values": ["inactive"]},
        ),
        DocumentTable(id="docs", paths=["docs/*.yaml"], schema_path="schemas/rule.schema.yaml"),
    ]
    source = make_served_source(root=root, config=make_source_config(documents=tables))
    target = make_target(source)
    store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
    documents = store.load(target).documents
    # 実行
    flags = exclusion_flags(target, documents, store=store, today=TODAY)
    # 検証
    assert [document.id for document in documents] == ["a1", "a2", "d1"]
    assert flags == [False, True, False]


def test_exclusion_flags_when_no_exclusion(
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    make_document: Callable[..., Document],
) -> None:
    """除く条件を持たない配信元（正常系）。"""
    from project_index.features.search.filters import exclusion_flags

    class _FailingStore:
        """呼ばれたら失敗する文書のストアの偽物。"""

        def row_schema(self, target: object, kind: str) -> dict[str, object]:
            raise AssertionError(f"row_schema を呼んだ: {kind}")

    # 準備
    target = make_target(make_served_source())
    documents = [make_document(id="doc-1"), make_document(id="doc-2")]
    # 実行
    flags = exclusion_flags(target, documents, store=_FailingStore(), today=TODAY)  # type: ignore[arg-type]
    # 検証
    assert flags == [False, False]

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest

from project_index.features.search.filters import (
    check_filter,
    compile_regex,
    match_filter,
    parse_compare_value,
)
from project_index.features.search.types import Condition, Group, LineRange, OrderKey, SearchRequest

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.documents.types import Document

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

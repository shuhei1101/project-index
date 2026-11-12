"""検索の条件の確かめと照合。"""

from __future__ import annotations

import difflib
import re
import unicodedata
from datetime import UTC, date, datetime, timedelta
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from project_index.features.search.fields import as_datetime, field_values
from project_index.features.search.types import Condition, Group, SearchRequest
from project_index.shared.errors import Violation

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from project_index.features.documents.types import Document

COMPARE_OPS = ("gt", "gte", "lt", "lte")
NO_VALUE_OPS = ("exists", "not_exists")
MATCHES_FIELD = "@matches"
RELATIVE_DAYS = re.compile(r"^(?P<sign>[+-])(?P<days>\d+)d$")
CLOSE_FIELDS = 3
# 束が持つ `and`・`or`・`not` のうち、値を持たないキーの数（持つのは 1 つだけ）
GROUP_EMPTY_KEYS = 2


def normalize(text: str) -> str:
    """NFKC と `casefold` をした文字列にする。"""
    return unicodedata.normalize("NFKC", text).casefold()


def compile_regex(value: str, *, case_sensitive: bool) -> re.Pattern[str]:
    """`regex` の値を、各行に当たる正規表現にする。"""
    # ^・$ を各行の先頭・末尾に当てる。大文字小文字を区別しないときは IGNORECASE を加える
    flags = re.MULTILINE if case_sensitive else re.MULTILINE | re.IGNORECASE
    return re.compile(value, flags)


def _midnight(day: date) -> datetime:
    """日付の 0 時（UTC）にする。"""
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def parse_compare_value(value: str, field_type: str, *, today: date) -> Any:  # noqa: ANN401
    """条件の値を項目の型で解釈する。"""
    try:
        if field_type == "date":
            if value == "today":
                return _midnight(today)
            if relative := RELATIVE_DAYS.match(value):
                days = int(relative.group("days"))
                return _midnight(
                    today + timedelta(days=days if relative.group("sign") == "+" else -days)
                )
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        if field_type == "number":
            return float(value)
    except ValueError as error:
        msg = f"{value} を {field_type} として読み込めません"
        raise ValueError(msg) from error
    return value


def _walk(node: Condition | Group, path: str) -> list[tuple[str, Condition | Group]]:
    """条件の木をたどり、(引数のパス, 節) を上から並べる。"""
    nodes: list[tuple[str, Condition | Group]] = [(path, node)]
    if isinstance(node, Group):
        for key, children in (("and", node.all_of), ("or", node.any_of)):
            for index, child in enumerate(children or []):
                nodes.extend(_walk(child, f"{path}.{key}[{index}]"))
        if node.not_ is not None:
            nodes.extend(_walk(node.not_, f"{path}.not"))
    return nodes


def _unknown_field(path: str, field: str, fields: Mapping[str, str]) -> Violation:
    """知らない項目の違反を、近い項目を添えて作る。"""
    close = difflib.get_close_matches(field, list(fields), n=CLOSE_FIELDS)
    fix = (
        f"近い項目: {', '.join(close)}" if close else "describe で使用できる項目を確認してください"
    )
    return Violation(path=path, rule=f"知らない項目です（{field}）", fix=fix)


def _check_condition(condition: Condition, path: str, fields: Mapping[str, str]) -> list[Violation]:
    """条件 1 つの項目と値を確かめる。"""
    violations: list[Violation] = []
    if condition.field == MATCHES_FIELD:
        # 文書ごとの数なので、条件ではなく fields・order_by に渡す
        return [
            Violation(
                path=f"{path}.field",
                rule="@matches は条件に使用できません",
                fix="fields か order_by に指定してください",
            )
        ]
    if condition.field not in fields:
        violations.append(_unknown_field(f"{path}.field", condition.field, fields))
    if condition.op in NO_VALUE_OPS:
        return violations
    if not condition.values:
        violations.append(
            Violation(
                path=f"{path}.values",
                rule="値が 1 つ以上要ります",
                fix="values に値を指定してください",
            )
        )
    for index, value in enumerate(condition.values):
        if condition.op == "regex":
            try:
                compile_regex(value, case_sensitive=condition.case_sensitive)
            except re.error as error:
                violations.append(
                    Violation(
                        path=f"{path}.values[{index}]",
                        rule=f"正規表現として読み込めません（{error}）",
                    )
                )
        elif condition.op in COMPARE_OPS and condition.field in fields:
            try:
                parse_compare_value(value, fields[condition.field], today=date.today())  # noqa: DTZ011
            except ValueError as error:
                violations.append(
                    Violation(
                        path=f"{path}.values[{index}]",
                        rule=str(error),
                        fix=f"{fields[condition.field]} の値にしてください",
                    )
                )
    return violations


def check_filter(request: SearchRequest, fields: Mapping[str, str]) -> list[Violation]:
    """条件・並べ替え・集計の項目と値が使えるかを確かめる。"""
    violations: list[Violation] = []
    if request.filter is not None:
        for path, node in _walk(request.filter, "filter"):
            if isinstance(node, Condition):
                violations.extend(_check_condition(node, path, fields))
            elif [node.all_of, node.any_of, node.not_].count(None) != GROUP_EMPTY_KEYS:
                violations.append(
                    Violation(
                        path=path,
                        rule="and・or・not のどれか 1 つだけを持ってください",
                        fix="条件を and・or・not の中に並べてください",
                    )
                )
    for index, key in enumerate(request.order_by or []):
        if key.field not in fields:
            violations.append(_unknown_field(f"order_by[{index}].field", key.field, fields))
    if request.group_by == MATCHES_FIELD:
        violations.append(
            Violation(
                path="group_by",
                rule="@matches は集計に使用できません",
                fix="fields か order_by に指定してください",
            )
        )
    elif request.group_by is not None and request.group_by not in fields:
        violations.append(_unknown_field("group_by", request.group_by, fields))
    violations.extend(_check_body_range(request))
    return violations


def _check_body_range(request: SearchRequest) -> list[Violation]:
    """本文の一部を返す引数（sections・lines）の組み合わせを確かめる。"""
    violations: list[Violation] = []
    if request.sections is not None and request.lines is not None:
        violations.append(
            Violation(
                path="sections",
                rule="sections と lines は同時に指定できません",
                fix="どちらか一方にしてください",
            )
        )
    if request.view != "full" and (request.sections is not None or request.lines is not None):
        violations.append(
            Violation(
                path="sections" if request.sections is not None else "lines",
                rule="view: full のときだけ指定できます",
                fix="view に full を指定してください",
            )
        )
    return violations


def _text(value: Any) -> str:  # noqa: ANN401
    """比べる値を文字列にする。"""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _comparable(value: Any, field_type: str) -> Any:  # noqa: ANN401
    """文書の値を項目の型にそろえる（そろえられなければ `None`）。"""
    try:
        if field_type == "date":
            parsed = as_datetime(value)
            if parsed is None:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        if field_type == "number":
            return float(value)
    except TypeError, ValueError:
        return None
    return _text(value)


def _nfkc_unless(condition: Condition, text: str) -> str:
    """区別しない条件なら NFKC にした文字列を返す。"""
    return text if condition.case_sensitive else unicodedata.normalize("NFKC", text)


def _test(
    condition: Condition, values: list[Any], expected: str, field_type: str, today: date
) -> bool:
    """比べる値 1 つが、文書の値の並びのどれかに当たるかを返す。"""
    op = condition.op
    fold: Callable[[str], str] = (lambda text: text) if condition.case_sensitive else normalize
    if op == "regex":
        pattern = compile_regex(expected, case_sensitive=condition.case_sensitive)
        # パターンには正規化をかけず、区別しないときは文書の値だけを NFKC にする
        return any(pattern.search(_nfkc_unless(condition, _text(value))) for value in values)
    if op in COMPARE_OPS:
        target = parse_compare_value(expected, field_type, today=today)
        for value in values:
            current = _comparable(value, field_type)
            if current is None:
                continue
            if (
                (op == "gt" and current > target)
                or (op == "gte" and current >= target)
                or (op == "lt" and current < target)
                or (op == "lte" and current <= target)
            ):
                return True
        return False
    wanted = fold(expected)
    texts = [fold(_text(value)) for value in values]
    if op == "glob":
        return any(PurePosixPath(text).full_match(wanted) for text in texts)
    positive = (
        op
        if op in ("eq", "prefix", "suffix", "contains")
        else {"ne": "eq", "not_contains": "contains"}[op]
    )
    checks: dict[str, Callable[[str], bool]] = {
        "eq": lambda text: text == wanted,
        "prefix": lambda text: text.startswith(wanted),
        "suffix": lambda text: text.endswith(wanted),
        "contains": lambda text: wanted in text,
    }
    found = any(checks[positive](text) for text in texts)
    return not found if op in ("ne", "not_contains") else found


def _match_condition(
    condition: Condition, document: Document, fields: Mapping[str, str], today: date
) -> bool:
    """条件 1 つに当たるかを判定する。"""
    values = field_values(document, condition.field)
    if condition.op == "exists":
        return bool(values)
    if condition.op == "not_exists":
        return not values
    field_type = fields.get(condition.field, "string")
    results = (
        _test(condition, values, expected, field_type, today) for expected in condition.values
    )
    return all(results) if condition.match == "all" else any(results)


def match_filter(
    node: Condition | Group | None,
    document: Document,
    *,
    fields: Mapping[str, str],
    today: date,
) -> bool:
    """文書が条件の木に当たるかを判定する。"""
    if node is None:
        return True
    if isinstance(node, Group):
        if node.all_of is not None:
            return all(
                match_filter(child, document, fields=fields, today=today) for child in node.all_of
            )
        if node.any_of is not None:
            return any(
                match_filter(child, document, fields=fields, today=today) for child in node.any_of
            )
        if node.not_ is not None:
            return not match_filter(node.not_, document, fields=fields, today=today)
        return True
    return _match_condition(node, document, fields, today)


def match_words(document: Document, words: Sequence[str]) -> bool:
    """空白で区切った語を全て含む文書かを判定する。"""
    haystack = "\n".join(
        normalize(_text(value)) for value in [*field_values(document, "*"), document.id]
    )
    return all(word in haystack for word in words)

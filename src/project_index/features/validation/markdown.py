"""変えた Markdown の値を mdmark の点検に通し、描画時の書き方の警告を違反にする。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from jsonschema import Draft202012Validator
from jsonschema import validators as jsonschema_validators
from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for
from referencing.exceptions import Unresolvable

from project_index.integrations.mdmark import MdmarkUnavailableError, check_markdown
from project_index.shared.errors import Violation
from project_index.shared.schema_check import format_path

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping
    from pathlib import Path

logger = logging.getLogger(__name__)

MARKDOWN_MEDIA_TYPE = "text/markdown"
BLOCKING_KINDS = frozenset({"diagram_invalid", "syntax_warning"})
MEDIA_TYPE_KEYWORD = "contentMediaType"


class _Validator(Protocol):
    """`extend` で作った検査器のうち使うメソッド。"""

    def iter_errors(self, instance: object) -> Iterator[ValidationError]:
        """値の誤りを並べる。"""
        ...


# 型スタブの `extend` は型を持たないため、検査器の型を返す関数として読む
_EXTEND: Callable[..., Callable[[dict[str, Any]], _Validator]] = vars(jsonschema_validators)[
    "extend"
]


@dataclass(frozen=True, slots=True, kw_only=True)
class UncheckedKey:
    """mdmark で点検できなかった Markdown のキーと理由。"""

    path: str
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MarkdownCheck:
    """文書 1 件の Markdown の値の点検の違反と、点検できなかったキー。"""

    violations: list[Violation]
    unchecked: list[UncheckedKey]
    # CLI が無い・制限時間を超えたときの理由。同じ書き込みの後の文書へ引き継ぐ
    stopped: str | None = None


def _mark_markdown(
    validator: object,
    value: object,
    instance: object,
    schema: Mapping[str, Any],
) -> Iterator[ValidationError]:
    """`contentMediaType` が Markdown の文字列の位置に、目印の誤りを出す。"""
    if value == MARKDOWN_MEDIA_TYPE and isinstance(instance, str):
        yield ValidationError(MARKDOWN_MEDIA_TYPE)


def _marked(errors: Iterable[ValidationError]) -> Iterator[ValidationError]:
    """目印の誤りを、`anyOf`・`oneOf` などにまとめられた誤りの中まで再帰して取り出す。"""
    for error in errors:
        if error.validator == MEDIA_TYPE_KEYWORD:
            yield error
        elif error.context:
            yield from _marked(error.context)


def markdown_values(data: Mapping[str, Any], schema: Mapping[str, Any]) -> dict[str, str]:
    """文書の内容のうち、スキーマで Markdown と宣言した文字列の値を項目のパスごとに返す。"""
    if not schema:
        return {}
    base = validator_for(dict(schema), default=Draft202012Validator)
    # contentMediaType の処理だけを目印を出す処理に差し替える
    marker_class = _EXTEND(base, validators={MEDIA_TYPE_KEYWORD: _mark_markdown})
    validator = marker_class(dict(schema))
    # 目印は文字列の値にだけ出すので、instance は str
    try:
        return {
            format_path(error.absolute_path): str(error.instance)
            for error in _marked(validator.iter_errors(dict(data)))
        }
    except Unresolvable as error:
        # 解決できない `$ref` はスキーマの検査が違反にするので、Markdown のキーは無いものとする
        logger.warning("Markdown のキーを取り出せなかった（%s）", error.ref)
        return {}


def changed_markdown(
    data: Mapping[str, Any], previous: Mapping[str, Any] | None, schema: Mapping[str, Any]
) -> dict[str, str]:
    """操作の前と値が違う Markdown のキーの値を返す（`previous` が `None` なら全て）。"""
    current = markdown_values(data, schema)
    before = markdown_values(previous, schema) if previous is not None else {}
    return {path: current[path] for path in sorted(current) if before.get(path) != current[path]}


def check_markdown_values(
    values: Mapping[str, str],
    *,
    cwd: Path,
    timeout_sec: float,
    stopped: str | None = None,
) -> MarkdownCheck:
    """値ごとに mdmark の点検を通し、書き方の警告を違反に、点検できなかった値を記録する。"""
    violations: list[Violation] = []
    unchecked: list[UncheckedKey] = []
    for path, text in values.items():
        # 同じ書き込みの前の点検で止めた: mdmark を呼ばずに点検できなかったキーにする
        if stopped is not None:
            unchecked.append(UncheckedKey(path=path, reason=stopped))
            continue
        try:
            findings = check_markdown(text, cwd=cwd, timeout_sec=timeout_sec)
        except MdmarkUnavailableError as error:
            logger.info("mdmark で点検できなかった（%s・%s）", path, error.reason)
            unchecked.append(UncheckedKey(path=path, reason=error.reason))
            # CLI が無い・制限時間を超えた: 残りの値も呼ばない
            if not error.continuable:
                stopped = error.reason
            continue
        # 描画時の書き方の警告だけを違反にし、ほかの種類は書き込みを止めない
        violations.extend(
            Violation(
                path=path, rule=f"mdmark の {item.kind}（{item.line} 行目）", fix=item.message
            )
            for item in findings
            if item.kind in BLOCKING_KINDS
        )
    return MarkdownCheck(violations=violations, unchecked=unchecked, stopped=stopped)

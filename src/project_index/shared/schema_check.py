"""JSON Schema の違反を、項目のパスつきの `Violation` にする。"""
# pyright: reportUnknownArgumentType=warning, reportUnknownMemberType=warning, reportUnknownVariableType=warning

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator

from project_index.shared.errors import Violation

if TYPE_CHECKING:
    from jsonschema.exceptions import ValidationError
    from referencing import Registry


def format_path(parts: Iterable[str | int]) -> str:
    """`sources[0].config` の形の項目のパスにする。"""
    result = ""
    for part in parts:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += f".{part}" if result else str(part)
    return result


def _as_list(value: Any) -> list[str]:  # noqa: ANN401
    """`required` の値を文字列の並びとして読む。"""
    return [str(item) for item in value] if isinstance(value, list) else []


def _from_error(error: ValidationError) -> list[Violation]:
    """jsonschema の誤り 1 つを違反の並びにする（必須のキーと知らないキーは 1 キーずつ）。"""
    base = list(error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, dict):
        return [
            Violation(path=format_path([*base, key]), rule="必須のキーが無い")
            for key in _as_list(error.validator_value)
            if key not in error.instance
        ]
    if error.validator == "additionalProperties" and isinstance(error.instance, dict):
        schema = error.schema
        known = set(schema.get("properties", {})) if isinstance(schema, Mapping) else set()
        return [
            Violation(path=format_path([*base, key]), rule="知らないキー")
            for key in error.instance
            if key not in known
        ]
    path = format_path(base) or "$"
    if error.validator == "type":
        return [Violation(path=path, rule=f"型が違う（期待: {error.validator_value}）")]
    if error.validator == "enum":
        return [Violation(path=path, rule=f"次のどれかにする: {error.validator_value}")]
    return [Violation(path=path, rule=error.message)]


def schema_violations(
    schema: Mapping[str, Any],
    value: Any,  # noqa: ANN401
    *,
    registry: Registry[Any] | None = None,
) -> list[Violation]:
    """スキーマの違反を全て集める（`registry` は別のファイルを `$ref` で指すスキーマの解決先）。"""
    validator = (
        Draft202012Validator(dict(schema))
        if registry is None
        else Draft202012Validator(dict(schema), registry=registry)
    )
    errors = sorted(
        validator.iter_errors(value), key=lambda item: list(map(str, item.absolute_path))
    )
    violations: list[Violation] = []
    for error in errors:
        violations.extend(_from_error(error))
    return violations

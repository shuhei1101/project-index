"""JSON Schema の違反を、項目のパスつきの `Violation` にする。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from jsonschema import Draft202012Validator

from project_index.shared.errors import Violation
from project_index.shared.narrowing import is_dict, is_list

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

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


def _as_list(value: object) -> list[str]:
    """`required` の値を文字列の並びとして読む。"""
    return [str(item) for item in value] if is_list(value) else []


def _properties(schema: object) -> set[object]:
    """スキーマの `properties` のキーの集合（無ければ空）。"""
    properties = schema.get("properties") if is_dict(schema) else None
    return set(properties) if is_dict(properties) else set()


def _from_error(error: ValidationError) -> list[Violation]:
    """jsonschema の誤り 1 つを違反の並びにする（必須のキーと知らないキーは 1 キーずつ）。"""
    base = list(error.absolute_path)
    instance: object = error.instance
    if error.validator == "required" and is_dict(instance):
        return [
            Violation(path=format_path([*base, key]), rule="必須のキーが無い")
            for key in _as_list(error.validator_value)
            if key not in instance
        ]
    if error.validator == "additionalProperties" and is_dict(instance):
        known = _properties(error.schema)
        return [
            Violation(path=format_path([*base, str(key)]), rule="知らないキー")
            for key in instance
            if key not in known
        ]
    path = format_path(base) or "$"
    if error.validator == "type":
        return [Violation(path=path, rule=f"型が違う（期待: {error.validator_value}）")]
    if error.validator == "enum":
        return [Violation(path=path, rule=f"次のどれかにする: {error.validator_value}")]
    return [Violation(path=path, rule=error.message)]


def schema_violations(
    schema: object,
    value: object,
    *,
    registry: Registry[Any] | None = None,
) -> list[Violation]:
    """スキーマの違反を全て集める（`registry` は別のファイルを `$ref` で指すスキーマの解決先）。"""
    if not is_dict(schema):
        msg = "スキーマが辞書ではありません"
        raise TypeError(msg)
    keyed = cast("dict[str, Any]", schema)
    validator = (
        Draft202012Validator(keyed)
        if registry is None
        else Draft202012Validator(keyed, registry=registry)
    )
    errors = sorted(
        _iter_errors(validator, value), key=lambda item: list(map(str, item.absolute_path))
    )
    violations: list[Violation] = []
    for error in errors:
        violations.extend(_from_error(error))
    return violations


def _iter_errors(validator: Draft202012Validator, value: object) -> list[ValidationError]:
    """検査器の誤りを並べる。"""
    # 型スタブの iter_errors は、引数を JSON の値の型に限る多重定義と、型の無い多重定義を持つ。
    # YAML から読んだ値は型が決まらないため、型の無い呼び出しとして扱う
    iterate: Callable[[object], Iterator[ValidationError]] = cast("Any", validator).iter_errors
    return list(iterate(value))

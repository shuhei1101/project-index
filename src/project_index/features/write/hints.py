"""`write_docs` のスキーマの違反に、違反した項目のスキーマの説明を添える。"""
# pyright: reportUnknownMemberType=warning, reportUnknownVariableType=warning

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from jsonschema import FormatChecker
from jsonschema.validators import Draft202012Validator, validator_for

from project_index.features.validation.rules import REQUIRED_MESSAGE, ROOT_PATH
from project_index.features.write.types import WriteViolation
from project_index.shared.schema_check import format_path

if TYPE_CHECKING:
    from jsonschema.exceptions import ValidationError

    from project_index.shared.errors import Violation

HINT_KEYS = ("title", "description", "x-rules", "examples", "x-bad-examples")


def _definition(error: ValidationError) -> Any:  # noqa: ANN401
    """違反に添える定義を返す（`required` は無かったキーの定義、それ以外は違反した値に当てた定義）。"""
    if error.validator != "required":
        return error.schema
    matched = REQUIRED_MESSAGE.match(error.message)
    if matched is None:
        return None
    try:
        missing = str(ast.literal_eval(matched.group(1)))
    except ValueError, SyntaxError:
        return None
    properties = error.schema.get("properties") if isinstance(error.schema, Mapping) else None
    return properties.get(missing) if isinstance(properties, Mapping) else None


def _hint(definition: Any) -> dict[str, Any] | None:  # noqa: ANN401
    """定義から `HINT_KEYS` のうち持つキーだけを取り出す（1 つも無ければ `None`）。"""
    if not isinstance(definition, Mapping):
        return None
    hint = {key: definition[key] for key in HINT_KEYS if key in definition}
    return hint or None


def attach_schema_hints(
    violations: list[Violation], *, schema: Mapping[str, Any], data: Mapping[str, Any]
) -> list[WriteViolation]:
    """文書の検査の違反のうちスキーマの違反に、違反した項目のスキーマの説明を添える。"""
    hints: dict[tuple[str, str], dict[str, Any]] = {}
    # スキーマの検査と同じ検査器で違反を引き直し、`path`・`rule` の組で説明を控える
    if schema:
        validator_class = validator_for(dict(schema), default=Draft202012Validator)
        validator = validator_class(dict(schema), format_checker=FormatChecker())
        for error in validator.iter_errors(dict(data)):
            hint = _hint(_definition(error))
            if hint is not None:
                path = format_path(error.absolute_path) or ROOT_PATH
                hints.setdefault((path, error.message), hint)
    return [
        WriteViolation(
            path=violation.path,
            rule=violation.rule,
            fix=violation.fix,
            index=violation.index,
            doc=violation.doc,
            schema=hints.get((violation.path, violation.rule)),
        )
        for violation in violations
    ]

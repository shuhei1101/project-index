"""文書の検査の決まり。"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, Any

from jsonschema import FormatChecker
from jsonschema.validators import Draft202012Validator, validator_for

from project_index.shared.errors import Violation
from project_index.shared.narrowing import is_dict, is_list
from project_index.shared.schema_check import format_path

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from jsonschema.exceptions import ValidationError

SLUG_PATTERN = "[a-z0-9]+(?:-[a-z0-9]+)*"

ROOT_PATH = "$"
PLACEHOLDER = re.compile(r"(\{[^{}]*\})")
REQUIRED_MESSAGE = re.compile(r"^(.*) is a required property$")


def _schema_fix(error: ValidationError) -> str:
    """`required`・`enum`・`type` の誤りに、足りないキー・許す値・期待する型を添える。"""
    if error.validator == "required":
        matched = REQUIRED_MESSAGE.match(error.message)
        try:
            missing = str(ast.literal_eval(matched.group(1))) if matched else ""
        except ValueError, SyntaxError:
            missing = ""
        return f"キー {missing} を追加してください" if missing else ""
    value: object = error.validator_value
    if error.validator == "enum":
        return f"次のどれかにしてください: {_listed(value)}"
    if error.validator == "type":
        expected_text = _listed(value)
        return f"型を {expected_text} にしてください"
    return ""


def check_schema(data: Mapping[str, Any], schema: Mapping[str, Any]) -> list[Violation]:
    """文書の内容を種類の JSON Schema で検査する。"""
    if not schema:
        return []
    validator_class = validator_for(dict(schema), default=Draft202012Validator)
    validator = validator_class(dict(schema), format_checker=FormatChecker())
    violations = [
        Violation(
            path=format_path(error.absolute_path) or ROOT_PATH,
            rule=error.message,
            fix=_schema_fix(error),
        )
        for error in validator.iter_errors(dict(data))
    ]
    return sorted(violations, key=lambda violation: violation.path)


def _format_pattern(fmt: str, kind: str) -> tuple[str, str]:
    """`ids.format` を正規表現と、例の文字列にする。"""
    pattern = ""
    example = ""
    for part in PLACEHOLDER.split(fmt):
        if part == "{kind}":
            pattern += re.escape(kind)
            example += kind
        elif part == "{slug}":
            pattern += SLUG_PATTERN
            example += "example"
        elif PLACEHOLDER.fullmatch(part):
            pattern += "[^/]+"
            example += "x"
        else:
            pattern += re.escape(part)
            example += part
    return pattern, example


def check_id_format(doc_id: str, fmt: str | None, *, kind: str) -> list[Violation]:
    """新しく作る文書の ID が `ids.format` に合うかを確かめる。"""
    if fmt is None:
        return []
    pattern, example = _format_pattern(fmt, kind)
    if re.fullmatch(pattern, doc_id):
        return []
    return [
        Violation(
            path="id",
            rule="ids.format",
            fix=f"{fmt} の形式にしてください（例 {example}）",
        )
    ]


def _listed(value: object) -> str:
    """配列は要素を `, ` でつなぎ、それ以外は文字列にする。"""
    return ", ".join(map(str, value)) if is_list(value) else str(value)


def check_related(metadata: Mapping[str, Any], types: Sequence[str]) -> list[Violation]:
    """メタデータの `related` の各行が `to` と `related.types` の語の `type` を持つかを確かめる。"""
    if "related" not in metadata:
        return []
    related: object = metadata["related"]
    if not is_list(related):
        return [Violation(path="related", rule="配列にしてください")]
    violations: list[Violation] = []
    for index, row in enumerate(related):
        prefix = f"related[{index}]"
        if not is_dict(row):
            violations.append(
                Violation(path=prefix, rule="辞書（to と type を持つ）にしてください")
            )
            continue
        if not isinstance(row.get("to"), str):
            violations.append(
                Violation(path=f"{prefix}.to", rule="相手の文書の ID（文字列）が要ります")
            )
        if "source" in row and not isinstance(row["source"], str):
            violations.append(
                Violation(path=f"{prefix}.source", rule="配信元の ID（文字列）にしてください")
            )
        if row.get("type") not in types:
            violations.append(
                Violation(
                    path=f"{prefix}.type",
                    rule="related.types に無い種類です",
                    fix=f"次のどれかにしてください: {', '.join(types)}",
                )
            )
    return violations

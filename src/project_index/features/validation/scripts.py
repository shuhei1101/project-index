"""`validators[]` の出力の解釈。"""
# pyright: reportUnknownArgumentType=warning, reportUnknownMemberType=warning, reportUnknownVariableType=warning

from __future__ import annotations

import json
from typing import Any

from project_index.shared.errors import Violation

ROOT_PATH = "$"


def parse_validator_output(stdout: str, *, validator_id: str) -> list[Violation]:
    """`validators[]` の標準出力の JSON を違反の並びにする。"""
    text = stdout.strip()
    if not text:
        return []
    prefix = f"{validator_id}: "
    try:
        items: Any = json.loads(text)
    except json.JSONDecodeError:
        items = None
    if not isinstance(items, list):
        return [Violation(path=ROOT_PATH, rule=f"{prefix}出力が違反の配列の JSON ではありません")]
    violations: list[Violation] = []
    for item in items:
        if isinstance(item, dict):
            rule = item.get("rule") or item.get("message") or ""
            violations.append(
                Violation(
                    path=str(item.get("path") or ROOT_PATH),
                    rule=f"{prefix}{rule}",
                    fix=str(item.get("fix") or ""),
                )
            )
        else:
            violations.append(Violation(path=ROOT_PATH, rule=f"{prefix}{item}"))
    return violations

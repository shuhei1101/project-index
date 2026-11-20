"""直コミットで書き込む値の秘密の値の照合。

規則の正規表現は gitleaks の既定の規則集から移した。

Copyright (c) 2019 Zachary Rice

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from project_index.shared.narrowing import is_dict, is_list

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

# 種類の ID → 照合する正規表現。量指定子を入れ子にしない
SECRET_RULES: dict[str, re.Pattern[str]] = {
    "github-token": re.compile(
        r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82}"
    ),
    "aws-access-key": re.compile(r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}\b"),
    "slack-token": re.compile(
        r"xox[baprs]-[0-9A-Za-z-]{10,}|https://hooks\.slack\.com/services/[A-Za-z0-9+/]{43,}"
    ),
    "openai-api-key": re.compile(
        r"sk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20}"
    ),
    "anthropic-api-key": re.compile(r"sk-ant-(?:api03|admin01)-[A-Za-z0-9_-]{93}AA"),
    "private-key": re.compile(r"-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----"),
    # ローカル部の途中から照合し直さないよう、ローカル部の文字が前に無い位置からだけ始める
    "email-address": re.compile(
        r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
    ),
}
BODY_PATH = "@body"


@dataclass(frozen=True, slots=True, kw_only=True)
class SecretFinding:
    """検出した項目のパスと種類（値は持たない）。"""

    path: str
    kind: str


def scan_text(text: str) -> list[str]:
    """文字列を規則ごとに照合し、該当した種類を返す。"""
    return [kind for kind, pattern in SECRET_RULES.items() if pattern.search(text)]


def secret_findings(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any],
    *,
    body_before: str | None = None,
    body_after: str | None = None,
) -> list[SecretFinding]:
    """書き込む前後の文書の値を比べ、変わった値と本文のファイルの追加の行だけを照合する。"""
    old_leaves = dict(_string_leaves(before)) if before is not None else {}
    findings: list[SecretFinding] = []
    # 変わった文字列の葉だけを照合する
    for path, value in _string_leaves(after):
        if old_leaves.get(path) == value:
            continue
        findings.extend(SecretFinding(path=path, kind=kind) for kind in scan_text(value))
    # 本文のファイルは、書き込む前に無かった行だけを照合する
    if body_after is not None:
        added = _added_lines(body_before or "", body_after)
        findings.extend(SecretFinding(path=BODY_PATH, kind=kind) for kind in scan_text(added))
    return list(dict.fromkeys(findings))


def _string_leaves(value: object, prefix: str = "") -> Iterator[tuple[str, str]]:
    """文字列の葉を、項目のパス（配列は添字）と値の組でたどる。"""
    if isinstance(value, str):
        yield prefix, value
    elif is_dict(value):
        for key, child in value.items():
            yield from _string_leaves(child, f"{prefix}.{key}" if prefix else str(key))
    elif is_list(value):
        for index, child in enumerate(value):
            yield from _string_leaves(child, f"{prefix}[{index}]")


def _added_lines(before: str, after: str) -> str:
    """後の内容のうち、前の内容に無い行をつないで返す。"""
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), n=0, lineterm="")
    # 見出しの `+++` を除き、追加の行だけを集める
    return "\n".join(
        line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")
    )

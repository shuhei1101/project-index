"""mdmark の CLI の `check --text -` による Markdown の点検。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from project_index.integrations.scripts import (
    ScriptFailedError,
    ScriptNotFoundError,
    ScriptTimeoutError,
    run_script,
)

if TYPE_CHECKING:
    from pathlib import Path

MDMARK_CHECK_RUN = ("mdmark", "check", "--text", "-")
FINDING_PATTERN = re.compile(r"^-:(\d+): ([a-z_]+): (.*)$")
SUMMARY_PATTERN = re.compile(r"^ずれ (\d+) 件$")


@dataclass(frozen=True, slots=True, kw_only=True)
class MdmarkFinding:
    """`mdmark check --text -` が出したずれの 1 行。"""

    line: int
    kind: str
    message: str


class MdmarkUnavailableError(Exception):
    """mdmark の CLI で点検を終えられなかったことを表す。"""

    def __init__(self, reason: str, *, continuable: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        # False: CLI が無い・制限時間を超えた。同じ書き込みの残りの値も呼ばない
        self.continuable = continuable


def parse_check_output(stdout: str) -> list[MdmarkFinding] | None:
    """`mdmark check --text -` の標準出力をずれの並びにする（件数の行が無ければ `None`）。"""
    lines = [line for line in stdout.splitlines() if line.strip()]
    # 最後の行が件数の行でなければ、点検を終えていない
    if not lines or SUMMARY_PATTERN.match(lines[-1]) is None:
        return None
    findings: list[MdmarkFinding] = []
    for line in lines[:-1]:
        matched = FINDING_PATTERN.match(line)
        # ずれの形でない行は読まない
        if matched is None:
            continue
        findings.append(MdmarkFinding(line=int(matched[1]), kind=matched[2], message=matched[3]))
    return findings


def check_markdown(text: str, *, cwd: Path, timeout_sec: float) -> list[MdmarkFinding]:
    """Markdown の文字列を `mdmark check --text -` に通し、ずれの並びを返す。"""
    try:
        run_script(MDMARK_CHECK_RUN, cwd=cwd, stdin=text, timeout_sec=timeout_sec)
    except ScriptNotFoundError as error:
        msg = "mdmark の CLI が PATH に見つかりません"
        raise MdmarkUnavailableError(msg, continuable=False) from error
    except ScriptTimeoutError as error:
        msg = f"mdmark の点検が制限時間（{timeout_sec} 秒）を超えました"
        raise MdmarkUnavailableError(msg, continuable=False) from error
    except ScriptFailedError as error:
        findings = parse_check_output(error.stdout)
        # ずれがあると終了コード 1 で終わる。件数の行が無ければ点検を終えていない
        if findings is None:
            tail = error.reason.split("\n", 1)[1] if "\n" in error.reason else ""
            msg = (
                f"mdmark の点検が結果を出さずに終了コード {error.exit_code} で終わりました: {tail}"
            )
            raise MdmarkUnavailableError(
                msg,
                continuable=True,
            ) from error
        return findings
    return []

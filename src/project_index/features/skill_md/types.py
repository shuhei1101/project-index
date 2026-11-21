"""`project-index skill-md` が扱うエージェントフロー・組み立てた SKILL.md の型と例外。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentFlowFile:
    """読み込んだエージェントフロー 1 件と、配信元の直下からのパス。"""

    # 配信元の直下からのパス（POSIX）。検査のモードで配信元に同じ `id` が無い標準入力は `-`
    path: str
    data: dict[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillFile:
    """書き出す先と組み立てた中身。"""

    # 配信元の直下からの `skill.path`
    path: str
    # 末尾を改行 1 つで終える SKILL.md の全文
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Problem:
    """読み込み・検査・組み立てで見つけた 1 件の問題。"""

    # 原因のエージェントフローのパス（ほかの配信元のスキーマは `{source}:{path}@{ref}`）
    file: str
    # ファイルの中の項目のパス。ファイル全体は `$`
    path: str
    rule: str
    # 検査のモードの違反の `fix`
    fix: str = ""

    def line(self) -> str:
        """`{file}: {path}: {rule}` の 1 行を返却する。"""
        return f"{self.file}: {self.path}: {self.rule}"


class InvalidAgentFlowError(Exception):
    """読み込み・検査・組み立てで見つけた全ての問題を持つ例外。"""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__("\n".join(problem.line() for problem in problems))
        self.problems = problems

from __future__ import annotations

from project_index.features.skill_md.types import Problem


def test_problem_line() -> None:
    """ファイル・項目・理由をつなぐ（正常系）。"""
    # 準備
    problem = Problem(
        file="docs/agent-flow/a.yaml", path="skill.path", rule="配信元の外部を指しています"
    )
    # 実行
    line = problem.line()
    # 検証
    assert line == "docs/agent-flow/a.yaml: skill.path: 配信元の外部を指しています"

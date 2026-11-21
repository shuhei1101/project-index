"""`project-index skill-md` の処理（生成のモードの失敗だけを終了コードにし、検査のモードは違反を JSON で出す）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from project_index.features.skill_md.build import (
    build_skill_files,
    check_replacement,
    load_agent_flows,
    write_changed,
)
from project_index.features.skill_md.types import InvalidAgentFlowError

if TYPE_CHECKING:
    import argparse

# 生成のモードでエージェントフローかスキーマが読み込めない・合わない、`ref` が解決できない、
# `skill.path` が配信元の外部を指すときの終了コード
EXIT_SKILL_INVALID = 1


def _read_stdin() -> str:
    """標準入力を UTF-8 で全て読む。"""
    buffer = getattr(sys.stdin, "buffer", None)
    # バイト列を持つ標準入力は端末の文字コードによらず UTF-8 で読む
    if buffer is not None:
        return str(buffer.read().decode("utf-8"))
    return sys.stdin.read()


def run_skill_md(args: argparse.Namespace) -> int:
    """`--check` が無ければ SKILL.md を生成し、あれば標準入力のエージェントフローを検査する。"""
    root = Path.cwd()
    # 検査のモード: 違反を JSON で出し、違反の有無によらず 0 で終える
    if args.check:
        problems = check_replacement(root, _read_stdin())
        violations = [{"path": p.path, "rule": p.rule, "fix": p.fix} for p in problems]
        sys.stdout.write(json.dumps(violations, ensure_ascii=False) + "\n")
        return 0
    # 生成のモード（`args.paths` は受け取るが、生成の対象は絞らない）
    try:
        flows, schema = load_agent_flows(root)
        written = write_changed(root, build_skill_files(root, flows, schema=schema))
    except InvalidAgentFlowError as error:
        for problem in error.problems:
            print(problem.line(), file=sys.stderr)
        return EXIT_SKILL_INVALID
    for path in written:
        print(path)
    return 0

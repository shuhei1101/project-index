"""`project-index skill-md` の処理（生成のモードの失敗だけを終了コードにし、検査のモードは違反を JSON で出す）。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from project_index.features.skill_md.build import (
    build_skill_files,
    check_deletion,
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
# 値が `delete` のとき、検査のモードを削除の検査にする環境変数
VALIDATE_ON_ENV = "PROJECT_INDEX_VALIDATE_ON"
# 削除する文書の `id` を 1 行に 1 件で受け取る環境変数
DELETE_IDS_ENV = "PROJECT_INDEX_DELETE_IDS"


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
        text = _read_stdin()
        # 削除の検査: 削除する文書を除いて組み立てる
        if os.environ.get(VALIDATE_ON_ENV) == "delete":
            delete_ids = [line for line in os.environ.get(DELETE_IDS_ENV, "").splitlines() if line]
            problems = check_deletion(root, text, delete_ids)
        else:
            problems = check_replacement(root, text)
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

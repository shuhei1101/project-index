"""端末の設定の project-index の行が develop の worktree の dev-docs.yaml を指しているかを観測する。"""

import sys
from pathlib import Path

SETTINGS = Path.home() / ".config/dev-docs/settings.yaml"
CONFIG = Path("/mnt/c/Users/shuhe/repo/project-index/.claude/worktrees/develop/dev-docs.yaml")
NEW_LINE = f"    config: {CONFIG}\n"


def main() -> int:
    """観測した値を出し、効いていなければ 1 を返す。"""
    pointed = NEW_LINE in SETTINGS.read_text(encoding="utf-8")
    print(f"端末の設定の参照先: {'ok' if pointed else 'failed'}")
    exists = CONFIG.is_file()
    print(f"develop の worktree の dev-docs.yaml: {'ok' if exists else 'failed'}")
    return 0 if pointed and exists else 1


if __name__ == "__main__":
    sys.exit(main())

"""索引のサーバーが、クローンの HEAD の commit の後に起動し直し始めたことを確かめる。"""

import subprocess
import sys
import time
from datetime import datetime

sys.dont_write_bytecode = True

CLONE = "/home/shuhei2441/repo/project-index/.claude/worktrees/develop"
SERVER_LOG = "/home/shuhei2441/.local/state/project-index/logs/project-index.log"
RESTART_LINE = "再起動を始める（pid "
# ログの行頭の時刻の書式（logging の asctime。ローカル時刻）
LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_TIME_CHARS = 19
# 再起動の要求はログへすぐ書かれる。書き出しの遅れを 2 秒の間隔で 5 回まで待つ
INTERVAL_SEC = 2
ATTEMPTS = 5


def last_restart_line() -> str:
    """索引のサーバーのログの、再起動を始めた最後の行を返す（無ければ空文字）。"""
    with open(SERVER_LOG, encoding="utf-8") as log:
        lines = [line.strip() for line in log if RESTART_LINE in line]
    return lines[-1] if lines else ""


try:
    committed = subprocess.run(
        ["git", "-C", CLONE, "log", "-1", "--format=%ct", "HEAD"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.strip()
except (OSError, subprocess.SubprocessError) as error:
    print("クローンの HEAD の時刻: failed")
    print(f"git -C {CLONE} log -1 --format=%ct HEAD: {error}")
    sys.exit(1)
head_time = datetime.fromtimestamp(int(committed))
line = ""
for _ in range(ATTEMPTS):
    line = last_restart_line()
    if line and datetime.strptime(line[:LOG_TIME_CHARS], LOG_TIME_FORMAT) >= head_time:
        print(f"再起動を始めた行: ok（{line}）")
        sys.exit(0)
    time.sleep(INTERVAL_SEC)
print("再起動を始めた行: failed")
print(f"クローンの HEAD の時刻: {head_time}")
print(f"{SERVER_LOG} の再起動を始めた最後の行: {line or '（無し）'}")
sys.exit(1)

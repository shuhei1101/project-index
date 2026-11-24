"""索引のサーバーが、クローンの HEAD が今の commit へ移った後に起動し直し始めたことを確かめる。"""

import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True

CLONE = "/home/shuhei2441/repo/project-index/.claude/worktrees/develop"
SERVER_LOG = "/home/shuhei2441/.local/state/project-index/logs/project-index.log"
RESTART_LINE = "再起動を始める（pid "
# ログの行頭の時刻の書式（logging の asctime。ローカル時刻）
LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_TIME_CHARS = 19
# reflog の --date=unix の選択子（HEAD@{1795485157}）から時刻を取り出す
REFLOG_TIME = re.compile(r"@\{(\d+)\}")
# 再起動の要求はログへすぐ書かれる。書き出しの遅れを 2 秒の間隔で 5 回まで待つ
INTERVAL_SEC = 2
ATTEMPTS = 5


def last_restart_line() -> str:
    """索引のサーバーのログの、再起動を始めた最後の行を返す（無ければ空文字）。"""
    with open(SERVER_LOG, encoding="utf-8") as log:
        lines = [line.strip() for line in log if RESTART_LINE in line]
    return lines[-1] if lines else ""


try:
    moved = subprocess.run(
        ["git", "-C", CLONE, "reflog", "-1", "--date=unix", "--format=%gd"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.strip()
except (OSError, subprocess.SubprocessError) as error:
    print("クローンの HEAD が移った時刻: failed")
    print(f"git -C {CLONE} reflog -1 --date=unix --format=%gd: {error}")
    sys.exit(1)
match = REFLOG_TIME.search(moved)
if match is None:
    print("クローンの HEAD が移った時刻: failed")
    print(f"git -C {CLONE} reflog -1 --date=unix --format=%gd: {moved or '（出力無し）'}")
    sys.exit(1)
head_time = int(match.group(1))
line = ""
for _ in range(ATTEMPTS):
    line = last_restart_line()
    if line and time.mktime(time.strptime(line[:LOG_TIME_CHARS], LOG_TIME_FORMAT)) >= head_time:
        print(f"再起動を始めた行: ok（{line}）")
        sys.exit(0)
    time.sleep(INTERVAL_SEC)
print("再起動を始めた行: failed")
print(f"クローンの HEAD が移った時刻: {time.strftime(LOG_TIME_FORMAT, time.localtime(head_time))}")
print(f"{SERVER_LOG} の再起動を始めた最後の行: {line or '（無し）'}")
sys.exit(1)

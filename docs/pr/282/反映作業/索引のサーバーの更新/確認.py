"""稼働中の索引のサーバーが、修正を取り込んだコードで要求を処理していることを確かめる。"""

import sys
import time

sys.dont_write_bytecode = True

# 索引のサーバーのログと、要求を処理した行の目印。修正を取り込んだコードは行に executor= を出す
SERVER_LOG = "/home/shuhei2441/.local/state/project-index/logs/project-index.log"
REQUEST_LINE = "要求を処理した（"
FIXED_MARK = " executor="
# 取り直しは、起動し直しの上限 60 秒を 2 秒の間隔で割った回数。エージェントの要求で行は数秒ごとに増える
INTERVAL_SEC = 2
ATTEMPTS = 30


def last_request_line() -> str:
    """索引のサーバーのログの、要求を処理した最後の行を返す（無ければ空文字）。"""
    with open(SERVER_LOG, encoding="utf-8") as log:
        lines = [line.strip() for line in log if REQUEST_LINE in line]
    return lines[-1] if lines else ""


line = ""
for _ in range(ATTEMPTS):
    line = last_request_line()
    # 修正を取り込んだコードは、要求を処理した行に実行スロットを出す
    if FIXED_MARK in line:
        print(f"要求を処理した行の executor: ok（{line}）")
        sys.exit(0)
    time.sleep(INTERVAL_SEC)
print("要求を処理した行の executor: failed")
print(f"{SERVER_LOG} の要求を処理した最後の行（{ATTEMPTS} 回取り直した後）: {line or '（無し）'}")
sys.exit(1)

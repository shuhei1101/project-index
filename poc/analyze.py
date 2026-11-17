"""PoC の計測の 1 回分を集計する: 配信元ごとの 1 回目の応答と、文書の一覧の区間の内訳。"""

import json
import re
import sys
from pathlib import Path

run = Path(sys.argv[1])
t0 = float((run / "t0").read_text())
rows = [json.loads(line) for line in (run / "timing.jsonl").read_text().splitlines()]

# 画面の 1 回目・2 回目の応答時間
pages = {}
for line in (run / "dd2.out").read_text().splitlines():
    m = re.match(r"(\d) (\S+) (\d+)ms", line)
    if m:
        pages[(int(m[1]), m[2])] = int(m[3]) / 1000

def rel(t):
    return round(t - t0, 1)

checks = [r for r in rows if r["event"] == "source_check"]
last_check_end = max((r["start"] + r["wall"] for r in checks), default=None)
exp_begin = next((r["t"] for r in rows if r["event"] == "export_begin"), None)
exp_end = next((r["t"] for r in rows if r["event"] == "export_end"), None)
print(f"# {run.name}")
print(f"検査: {len(checks)} 件・最後の終了 {rel(last_check_end) if last_check_end else '-'} 秒"
      f" / 裏の書き出し: 開始 {rel(exp_begin) if exp_begin else '-'} 秒・終了 {rel(exp_end) if exp_end else '-'} 秒")
if last_check_end:
    print(f"POC_EXPORT_AT_OFFSET={last_check_end - t0:.2f}")

# 文書の一覧の要求（api_work の name が _documents）ごとの内訳
print("| 配信元 | 画面 1 回目 | 画面 2 回目 | 一覧の開始 | 読み込み待ち | スレッドの空き待ち | read_target | 書き出し（要求の中） | 排他の待ち | archive | 展開 | list_documents の残り | 一覧の経過 | 一覧の CPU |")
print("| --- | " + " | ".join(["---"] * 13) + " |")
ids = [sid for (rnd, sid) in pages if rnd == 1]
for sid in ids:
    works = [r for r in rows if r["event"] == "api_work" and r.get("source") == sid and r.get("name") == "_documents"]
    if not works:
        print(f"| {sid} | {pages.get((1, sid))} | {pages.get((2, sid))} | - |")
        continue
    w = works[0]
    s, e = w["start"], w["start"] + w["wall"]
    waits = [r for r in rows if r["event"] == "api_wait_loaded" and r.get("source") == sid and r["start"] <= s]
    wait = waits[-1]["wall"] if waits else 0
    inside = lambda ev: [r for r in rows if r["event"] == ev and r["thread"] == w["thread"] and s <= r["start"] <= e]
    rt = sum(r["wall"] for r in inside("docs_read_target"))
    ld = sum(r["wall"] for r in inside("docs_list_documents"))
    rev = sum(r["wall"] for r in inside("store_revision_root"))
    lock = sum(r["wall"] for r in inside("checkout_lock_wait"))
    arc = sum(r["wall"] for r in inside("checkout_archive"))
    ext = sum(r["wall"] for r in inside("checkout_extract"))
    print(f"| {sid} | {pages.get((1, sid))} | {pages.get((2, sid))} | {rel(s)} | {wait:.2f} | {w.get('queue', 0):.2f} | {rt:.2f} | {rev:.2f} | {lock:.2f} | {arc:.2f} | {ext:.2f} | {ld - rev:.2f} | {w['wall']:.2f} | {w['cpu']:.2f} |")

# 稼働中のプロセスの使用
live = [json.loads(line) for line in (run / "live.jsonl").read_text().splitlines()] if (run / "live.jsonl").exists() else []
over = []
for row in live:
    for pid, v in row.items():
        if isinstance(v, dict) and (v["cpu"] > 0.2 or max(v["read_bytes"] + v["write_bytes"], v["rchar"] + v["wchar"]) > 10_000_000):
            over.append((rel(row["t"]), pid, v))
loads = [float(r["load"]) for r in live]
print(f"稼働中のプロセスの閾値超え: {len(over)} 秒 {over[:5]}")
if loads:
    print(f"load average（1 分）: 最小 {min(loads)}・最大 {max(loads)}")

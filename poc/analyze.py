"""PoC: 1 回の計測の timing.jsonl と api.txt から、配信元ごとの内訳の表を作る。"""

import json
import sys
from collections import defaultdict
from pathlib import Path


def analyze(run: Path) -> dict[str, dict]:
    t0 = float((run / "t0").read_text())
    rows = [json.loads(line) for line in (run / "timing.jsonl").read_text().splitlines()]
    api = {}
    for line in (run / "api.txt").read_text().splitlines():
        source, n, code, total, _ = line.split()
        api[(source, int(n))] = float(total)
    out: dict[str, dict] = {}
    seen: dict[str, int] = defaultdict(int)
    rowload = {r["source"]: r for r in rows if r["event"] == "row_load"}
    # 文書の一覧の要求ごとに集める。読み込み待ちはイベントループのスレッド、処理は to_thread のスレッドで出る。
    # 処理のスレッドのイベントは、同じスレッドの api_work が出たときにその要求へ数える
    pending: dict[str, list[dict]] = defaultdict(list)
    waits: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        ev = r["event"]
        src = r.get("source")
        if ev == "api_wait" and r.get("name") == "_documents":
            seen[src] += 1
            key = f"{src}#{seen[src]}"
            out[key] = defaultdict(float, wait=r["wall"], wait_start=r["start"] - t0)
            waits[src].append(key)
            continue
        if ev in ("row_load", "export_skipped", "api_wait"):
            continue
        if ev == "api_work":
            if r.get("name") != "_documents":
                pending.pop(r["thread"], None)
                continue
            key = waits[src].pop(0)
            cur = out[key]
            cur["work"] = r["wall"]
            cur["work_cpu"] = r["cpu"]
            for e in pending.pop(r["thread"], []):
                name = e["event"]
                if name == "revision_table":
                    cur["ls_tree"] += e.get("ls_tree_wall", 0)
                    cur["load_file"] += e.get("load_wall", 0)
                    cur["load_cpu"] += e.get("load_cpu", 0)
                    cur["fresh"] += e.get("fresh_wall", 0)
                    cur["loaded"] += e.get("loaded", 0)
                    cur["cached"] += e.get("cached", 0)
                else:
                    cur[name] += e.get("wall", 0)
            continue
        pending[r["thread"]].append(r)
    for key, cur in out.items():
        src, n = key.split("#")
        cur["api"] = api.get((src, int(n)), 0.0)
        rl = rowload.get(src)
        if rl:
            cur["row_start"] = rl["start"] - t0
            cur["row_wall"] = rl["wall"]
            cur["row_cpu"] = rl["cpu"]
        explained = cur["wait"] + cur["work"]
        cur["explained"] = explained / cur["api"] if cur["api"] else 0
    return out


COLS = [
    ("api", "API"), ("wait", "読み込み待ち"), ("wait_start", "待ちの開始"), ("row_start", "行の読み始め"),
    ("row_wall", "行の経過"), ("row_cpu", "行の CPU"), ("read_target", "read_target"),
    ("revision_root", "書き出し"), ("archive", "archive"), ("extract", "展開"), ("file_dates", "日時"), ("walk_files", "walk_files"),
    ("ls_tree_files", "ls-tree のパス"), ("ls_tree", "ls-tree"), ("fresh", "照合"), ("load_file", "load_file"),
    ("load_cpu", "load_file の CPU"), ("loaded", "読んだ数"), ("cached", "キャッシュ"), ("list_build", "組み立て"),
    ("work", "処理"), ("work_cpu", "処理の CPU"), ("explained", "説明率"),
]


def table(out: dict[str, dict]) -> str:
    lines = ["| 要求 | " + " | ".join(c[1] for c in COLS) + " |", "| --- |" + " --- |" * len(COLS)]
    for key, cur in out.items():
        cells = []
        for c, _ in COLS:
            v = cur.get(c)
            cells.append("-" if v is None else (f"{v:.0f}" if c in ("loaded", "cached") else f"{v:.2f}"))
        lines.append(f"| {key} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    run = Path(sys.argv[1])
    out = analyze(run)
    print(f"# {run.name}\n")
    print("load average: 前 " + (run / "loadavg-before").read_text().split()[0] + "・後 " + (run / "loadavg-after").read_text().split()[0] + "\n")
    print(table(out))
    (run / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))

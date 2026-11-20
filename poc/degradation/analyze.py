"""PoC（#237）: 1 回の記録（load.jsonl・project-index.log・pyspy.txt）を 10 分ごとに集計する。

使い方: python analyze.py {記録のフォルダ} [--bucket 600]
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
from datetime import datetime
from pathlib import Path

LOAD_LINE = re.compile(
    r"^(\S+ \S+),\d+ .*ワークツリーを読み込んだ（([^・]+)・([^・]+)・([\d.]+) 秒）"
)


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))] if ordered else 0.0


def load_times(folder: Path, started: float) -> list[tuple[float, str, str, float]]:
    """ログからワークツリーの読み込みの（経過秒・配信元・worktree・秒）を取り出す。"""
    rows = []
    for path in sorted(folder.glob("project-index.log*"), reverse=True):
        for line in path.read_text(errors="replace").splitlines():
            match = LOAD_LINE.match(line)
            if match:
                at = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
                rows.append((at - started, match.group(2), match.group(3), float(match.group(4))))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("--bucket", type=float, default=600)
    args = parser.parse_args()
    folder = Path(args.folder)
    events = [json.loads(line) for line in (folder / "load.jsonl").read_text().splitlines()]
    started = min(e["at"] - e["t"] for e in events)
    bucket = lambda t: int(t // args.bucket)  # noqa: E731

    calls = collections.defaultdict(list)
    statuses = collections.defaultdict(collections.Counter)
    admin = collections.defaultdict(list)
    samples = collections.defaultdict(list)
    for e in events:
        if e["kind"] == "call":
            calls[bucket(e["t"])].append(e["sec"])
            statuses[bucket(e["t"])][e["status"]] += 1
        elif e["kind"] == "status":
            admin[bucket(e["t"])].append(e["sec"])
        elif e["kind"] == "sample":
            samples[bucket(e["t"])].append(e)

    loads = load_times(folder, started)
    # 配信元ごとの基準: 記録の中で最も短い読み込み
    floor = {}
    for _, source, _, sec in loads:
        floor[source] = min(sec, floor.get(source, sec))
    per_bucket_loads = collections.defaultdict(list)
    for t, source, _, sec in loads:
        per_bucket_loads[bucket(t)].append(sec / max(floor[source], 0.5))

    print("| 区間（分） | 呼び出し | ok | error | timeout | p50 秒 | p95 秒 | max 秒 | 読み込み 回 | 読み込みの倍率 max | status max 秒 | RSS MB | 上位のスレッド（CPU 秒/区間） |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for b in sorted(set(calls) | set(samples)):
        secs = calls.get(b, [])
        counter = statuses.get(b, collections.Counter())
        rss = max((s["rss_mb"] for s in samples.get(b, [])), default=0)
        cpu = collections.Counter()
        for s in samples.get(b, []):
            for name, ticks in s["cpu_ticks"].items():
                cpu[name.split(":")[0]] += ticks / 100
        top = " ".join(f"{n}={v:.0f}" for n, v in cpu.most_common(3))
        ratios = per_bucket_loads.get(b, [])
        print(
            f"| {b * args.bucket / 60:.0f}-{(b + 1) * args.bucket / 60:.0f} | {len(secs)} | {counter['ok']} | {counter['error']} | {counter['timeout']} "
            f"| {statistics.median(secs) if secs else 0:.1f} | {percentile(secs, 0.95):.1f} | {max(secs, default=0):.1f} "
            f"| {len(ratios)} | {max(ratios, default=0):.1f} | {max(admin.get(b, [0])):.1f} | {rss} | {top} |"
        )
    print()
    print("配信元ごとの読み込みの最短（秒）:", {k: round(v, 1) for k, v in sorted(floor.items())})


if __name__ == "__main__":
    main()

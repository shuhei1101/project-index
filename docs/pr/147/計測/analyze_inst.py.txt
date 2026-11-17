import json, sys
run = sys.argv[1]
ev = [json.loads(l) for l in open(f"/tmp/poc147/runs/{run}/timing.jsonl")]
reqs = sorted([e for e in ev if e["ev"] == "req"], key=lambda e: e["t0"])
units = sorted([e for e in ev if e["ev"] == "unit"], key=lambda e: e["t0"])
fg = sorted([(e["t"], 1 if e["ev"] == "fg_in" else -1) for e in ev if e["ev"] in ("fg_in", "fg_out")])
spans, depth, start = [], 0, None
for t, d in fg:
    if depth == 0 and d == 1: start = t
    depth += d
    if depth == 0 and d == -1: spans.append((start, t))
def in_fg(t): return any(a <= t <= b for a, b in spans)
order = [l.split()[1] for l in open(f"/tmp/poc147/runs/{run}/dd2.out") if l.startswith("1 ")]
page = {l.split()[1]: l.split()[2] for l in open(f"/tmp/poc147/runs/{run}/dd2.out") if l.startswith("1 ")}
firsts = {}
for r in reqs:
    firsts.setdefault(r["source"], r["t0"])
starts = [firsts[s] for s in order]
print("| 配信元 | 画面 | 要求の数 | 要求の間隔の最大 | 要求と重なった 1 件（応答中でない間に始まった分） | 重なった秒数 | 重なった 1 件の最長 |")
print("| --- | --- | --- | --- | --- | --- | --- |")
for i, src in enumerate(order):
    lo = starts[i]; hi = starts[i + 1] if i + 1 < len(order) else lo + 60
    rs = [r for r in reqs if lo <= r["t0"] < hi]
    gaps = [b["t0"] - a["t1"] for a, b in zip(rs, rs[1:])]
    hits = []
    for u in units:
        if u["t1"] < lo or u["t0"] > hi: continue
        ov = sum(max(0, min(u["t1"], r["t1"]) - max(u["t0"], r["t0"])) for r in rs)
        if ov > 0.001: hits.append((ov, u, not in_fg(u["t0"])))
    outside = [h for h in hits if h[2]]
    longest = max(hits, key=lambda h: h[1]["t1"] - h[1]["t0"], default=None)
    lw = f"{longest[1]['t1']-longest[1]['t0']:.2f} 秒（{longest[1]['where']}）" if longest else "-"
    print(f"| {src} | {page[src]} | {len(rs)} | {max(gaps, default=0):.2f} 秒 | {len(hits)} 件（{len(outside)} 件） | {sum(h[0] for h in hits):.2f} 秒（{sum(h[0] for h in outside):.2f} 秒） | {lw} |")
lens = sorted((u["t1"] - u["t0"], u["where"]) for u in units)
from collections import Counter
print("\n1 件の数", len(units), " 0.1 秒以上:", Counter(w for a, w in lens if a >= 0.1).most_common())
print("最長 5 件", [(round(a, 2), w) for a, w in lens[-5:]])

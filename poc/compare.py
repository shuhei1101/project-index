"""PoC: 構成ごとの 3 回の計測の中央値と、文書の一覧の応答の一致を比べる。"""

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from analyze import analyze  # noqa: E402

RUNS = Path("/tmp/poc171/runs")
CONFIGS = ["c0", "c1a", "c1b", "c2", "c12a", "c12b", "c3"]
SOURCES = "dev-docs claude-balancer aituber knowledge mdmark ai-monitor voice-input gui-support mindstella observability project-index alias-inject rule-inject shuhdev-gateway".split()
METRICS = [("api", "API"), ("wait", "読み込み待ち"), ("row_wall", "行の経過"), ("row_cpu", "行の CPU"),
           ("revision_root", "書き出し"), ("load_file", "load_file"), ("load_cpu", "load_file の CPU"), ("work", "処理")]


def runs_of(config: str) -> list[Path]:
    return sorted(p for p in RUNS.glob(f"{config}-*") if (p / "loadavg-after").exists())


def medians(config: str) -> dict[str, dict[str, float]]:
    results = [analyze(run) for run in runs_of(config)]
    out = {}
    for key in results[0] if results else []:
        out[key] = {m: statistics.median(r.get(key, {}).get(m, 0.0) for r in results) for m, _ in METRICS}
    return out


def loadavg(config: str) -> str:
    vals = []
    for run in runs_of(config):
        b = (run / "loadavg-before").read_text().split()[0]
        a = (run / "loadavg-after").read_text().split()[0]
        vals.append(f"{b}→{a}")
    return "・".join(vals)


def same_bodies(config: str) -> list[str]:
    """構成 0 の 1 回目と、構成の各回の 1 回目の応答が違う配信元を返す。"""
    base = RUNS / "c0-1" / "body"
    diffs = []
    for run in runs_of(config):
        for source in SOURCES:
            a = json.loads((base / f"{source}-1.json").read_text())
            b = json.loads((run / "body" / f"{source}-1.json").read_text())
            if a != b:
                diffs.append(f"{run.name}:{source}")
    return diffs


def main() -> None:
    meds = {c: medians(c) for c in CONFIGS if runs_of(c)}
    for c in meds:
        print(f"- {c}: 回数 {len(runs_of(c))}・load average（前→後）{loadavg(c)}・応答が構成 0 と違う配信元: {same_bodies(c) or 'なし'}")
    print()
    for metric, label in METRICS:
        print(f"### {label}（中央値・秒）\n")
        print("| 要求 | " + " | ".join(meds) + " |")
        print("| --- |" + " --- |" * len(meds))
        for source in SOURCES:
            for n in (1, 2):
                key = f"{source}#{n}"
                print(f"| {key} | " + " | ".join(f"{meds[c].get(key, {}).get(metric, 0):.2f}" for c in meds) + " |")
        print()


if __name__ == "__main__":
    main()

"""PoC: 配信元の行の読み込み（load_source）の段ごとの経過と CPU を、1 行ずつ順に（取り合い無しで）測る。

段: 先頭の設定の default_ref の読み込み（_entry_default_ref_config）・設定の読み込み（_read_configs）・
検証（_validate）・スクリプトの確認（_check_scripts_at / check_scripts）・スキーマの読み込み（_row_schemas）。
各段の中の YAML の読み込み（load_yaml）の時間も別に数える。
"""

import json
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

import project_index.features.sources.service as service
import project_index.shared.yaml_io as yaml_io
from project_index.features.settings.query import load_terminal_config
from project_index.features.sources.registry import terminal_lookup

STAGES = ["_entry_default_ref_config", "_read_configs", "_validate", "_check_scripts_at", "check_scripts", "_row_schemas"]
acc: dict[str, float] = defaultdict(float)
local = threading.local()


def wrap(module, name, label):
    original = getattr(module, name)

    def inner(*args, **kwargs):
        w0, c0 = time.perf_counter(), time.thread_time()
        try:
            return original(*args, **kwargs)
        finally:
            acc[f"{label}.wall"] += time.perf_counter() - w0
            acc[f"{label}.cpu"] += time.thread_time() - c0

    setattr(module, name, inner)


for stage in STAGES:
    wrap(service, stage, stage)
wrap(service, "load_yaml", "load_yaml")
wrap(yaml_io, "load_yaml", "load_yaml_all")

terminal = load_terminal_config(Path(sys.argv[1]))
lookup = terminal_lookup(terminal)
out = {}
for index, entry in enumerate(terminal.sources):
    acc.clear()
    w0, c0 = time.perf_counter(), time.thread_time()
    service.load_source(entry, index=index, lookup=lookup)
    row = {"wall": time.perf_counter() - w0, "cpu": time.thread_time() - c0, **acc}
    out[entry.id or str(index)] = row
    print(entry.id, f"{row['wall']:.2f}/{row['cpu']:.2f}", " ".join(f"{s}={acc.get(s + '.wall', 0):.2f}/{acc.get(s + '.cpu', 0):.2f}" for s in STAGES), f"load_yaml(service)={acc.get('load_yaml.wall', 0):.2f}", flush=True)
Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=1))

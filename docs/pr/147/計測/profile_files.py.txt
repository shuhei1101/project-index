import sys, time, pathlib
from project_index.features.settings.query import load_terminal_config
from project_index.main import build_handlers
from project_index.features.documents import store as sm, loader as lm
from project_index.features.documents.store import check_sync
from project_index.shared import yaml_io
terminal = load_terminal_config(pathlib.Path(sys.argv[1]))
h = build_handlers(terminal); h.registry.load(terminal)
rec = []
real = sm.load_file
yl = {"t": 0.0}
real_yaml = lm.load_yaml if hasattr(lm, "load_yaml") else None
def tyaml(*a, **k):
    t = time.thread_time(); r = real_yaml(*a, **k); yl["t"] += time.thread_time() - t; return r
if real_yaml: lm.load_yaml = tyaml
def lf(root, path, table, **kw):
    yl["t"] = 0.0; t = time.thread_time(); r = real(root, path, table, **kw)
    rec.append((time.thread_time() - t, yl["t"], kw.get("source_id"), path, len(r[0])))
    return r
sm.load_file = lf
for src in h.registry.served():
    if src.id != "ai-monitor": continue
    check_sync(h.store, src)
rec.sort(reverse=True)
for c, y, s, p, n in rec[:6]:
    print(f"{s} {p} CPU {c:.2f} 秒 / YAML の解析 {y:.2f} 秒 / それ以外 {c-y:.2f} 秒 / 文書 {n} 件 / 1 文書あたり（解析以外） {(c-y)/max(n,1)*1000:.2f} ms")

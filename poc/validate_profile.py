"""PoC: 行の読み込みの検証（_validate）の中身を cProfile で測る。"""
import cProfile, io, pstats, sys
from pathlib import Path
import project_index.features.sources.service as service
from project_index.features.settings.query import load_terminal_config
from project_index.features.sources.registry import terminal_lookup

terminal = load_terminal_config(Path(sys.argv[1]))
lookup = terminal_lookup(terminal)
targets = sys.argv[2].split(",")
profiler = cProfile.Profile()
for index, entry in enumerate(terminal.sources):
    if entry.id in targets:
        profiler.runcall(service.load_source, entry, index=index, lookup=lookup)
s = io.StringIO()
pstats.Stats(profiler, stream=s).sort_stats("cumulative").print_stats(40)
print("\n".join(l.replace(str(Path.cwd()) + "/", "") for l in s.getvalue().splitlines() if l.strip()))

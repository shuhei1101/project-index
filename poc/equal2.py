"""PoC: 同じ commit で、構成 0 と構成 2・3b・5（2 回目）・全部入りの文書の一覧と、構成 3b・6 の行の読み込みの結果を比べる。"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from equal import diff_docs, listing  # noqa: E402

import project_index.features.sources.service as service  # noqa: E402
from project_index.features.documents.store import DocumentStore  # noqa: E402
from project_index.features.history.snapshot import SnapshotStore  # noqa: E402
from project_index.features.read.paths import read_target  # noqa: E402
from project_index.features.settings.query import load_terminal_config  # noqa: E402
from project_index.features.sources.registry import SourceRegistry, terminal_lookup  # noqa: E402

FLAGS = ["POC_CATFILE", "POC_YAML_C3B", "POC_COLLECT_CACHE", "POC_SCHEMA_CACHE", "POC_YAML_C"]


def with_flags(flags, fn):
    for f in FLAGS:
        os.environ.pop(f, None)
    for f in flags:
        os.environ[f] = "1"
    try:
        return fn()
    finally:
        for f in flags:
            os.environ.pop(f, None)


def row_result(entry, index, lookup):
    served, status = service.load_source(entry, index=index, lookup=lookup)
    return {
        "status": status.model_dump(mode="json") if hasattr(status, "model_dump") else str(status),
        "schemas": None if served is None else json.loads(json.dumps(served.schemas, sort_keys=True, default=str)),
    }


def main() -> None:
    terminal = load_terminal_config(Path(sys.argv[1]))
    lookup = terminal_lookup(terminal)
    result = {"rows": {}, "lists": {}}
    # 行の読み込み: 構成 0 と 3b・6・3b + 6
    for index, entry in enumerate(terminal.sources):
        if not entry.id or entry.id.startswith("mindstella-nandemo"):
            continue
        base = with_flags([], lambda: row_result(entry, index, lookup))
        result["rows"][entry.id] = {
            name: (with_flags(flags, lambda: row_result(entry, index, lookup)) == base)
            for name, flags in (("3b", ["POC_YAML_C3B"]), ("6", ["POC_SCHEMA_CACHE"]), ("3b+6", ["POC_YAML_C3B", "POC_SCHEMA_CACHE"]))
        }
        print("row", entry.id, result["rows"][entry.id], flush=True)
    registry = SourceRegistry()
    registry.load(terminal)
    with tempfile.TemporaryDirectory() as tmp:
        for source_id in sys.argv[2].split(","):
            target, _ = read_target(source_id, None, registry=registry)
            base = with_flags([], lambda: listing(target, DocumentStore(SnapshotStore(Path(tmp) / "b"))))
            out = {"commit": target.commit}
            for name, flags in (("2", ["POC_CATFILE"]), ("3b", ["POC_YAML_C3B"]), ("all", ["POC_CATFILE", "POC_YAML_C3B", "POC_COLLECT_CACHE"])):
                out[name] = with_flags(flags, lambda: diff_docs(base, listing(target, DocumentStore(SnapshotStore(Path(tmp) / name)))))

            # 構成 5: 同じストアで 2 回目（照合の保持を使う）
            def twice():
                store = DocumentStore(SnapshotStore(Path(tmp) / "5"))
                listing(target, store)
                return diff_docs(base, listing(target, store))

            out["5"] = with_flags(["POC_COLLECT_CACHE"], twice)
            result["lists"][source_id] = out
            print("list", source_id, target.commit[:8], {k: len(v) for k, v in out.items() if k != "commit"}, flush=True)
    Path(sys.argv[3]).write_text(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

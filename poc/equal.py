"""PoC: 同じ commit で、書き出し（構成 0）と cat-file（構成 2）、pure と C の YAML（構成 3）の文書の一覧を比べる。

1 つのプロセスの中で、同じ Target（解いた commit を固定）を 3 通りで読み、文書の一覧の応答を比べる。
"""

import json
import os
import sys
import tempfile
from pathlib import Path

from project_index.features.documents.store import DocumentStore
from project_index.features.history.snapshot import SnapshotStore
from project_index.features.read.paths import read_target
from project_index.features.read.service import list_documents
from project_index.features.settings.query import load_terminal_config
from project_index.features.sources.registry import SourceRegistry


def listing(target, store) -> dict:
    return list_documents(target, store=store, values=True, common_keys=True).model_dump(mode="json")


def diff_docs(a: dict, b: dict) -> list[str]:
    da = {d["id"]: d for d in a["documents"]}
    db = {d["id"]: d for d in b["documents"]}
    out = [f"{k}: 片方だけ" for k in sorted(set(da) ^ set(db))]
    for k in sorted(set(da) & set(db)):
        if da[k] != db[k]:
            keys = sorted(x for x in set(da[k]) | set(db[k]) if da[k].get(x) != db[k].get(x))
            detail = keys
            if "value" in keys:
                va, vb = da[k]["value"] or {}, db[k]["value"] or {}
                detail = [*keys, "value:" + ",".join(sorted(x for x in set(va) | set(vb) if va.get(x) != vb.get(x)))]
            out.append(f"{k}: {detail}")
    return out


def main() -> None:
    terminal = load_terminal_config(Path(sys.argv[1]))
    registry = SourceRegistry()
    registry.load(terminal)
    result = {}
    with tempfile.TemporaryDirectory() as tmp:
        for source_id in sys.argv[2].split(","):
            target, _ = read_target(source_id, None, registry=registry)
            os.environ.pop("POC_CATFILE", None)
            os.environ.pop("POC_YAML_C", None)
            base = listing(target, DocumentStore(SnapshotStore(Path(tmp) / "s0")))
            os.environ["POC_CATFILE"] = "1"
            cat = listing(target, DocumentStore(SnapshotStore(Path(tmp) / "s2")))
            os.environ.pop("POC_CATFILE")
            os.environ["POC_YAML_C"] = "1"
            yc = listing(target, DocumentStore(SnapshotStore(Path(tmp) / "s3")))
            os.environ.pop("POC_YAML_C")
            result[source_id] = {
                "commit": target.commit,
                "documents": len(base["documents"]),
                "catfile": diff_docs(base, cat),
                "yaml_c": diff_docs(base, yc),
            }
            print(source_id, target.commit[:8], len(base["documents"]), "cat-file の差", len(result[source_id]["catfile"]), "C の YAML の差", len(result[source_id]["yaml_c"]), flush=True)
    Path(sys.argv[3]).write_text(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

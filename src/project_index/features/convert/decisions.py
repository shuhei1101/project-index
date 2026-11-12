"""配信元の `decisions.folders` からの、設計書の `decisions` の検討事項の文書の検索。"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from project_index.features.sources.types import ServedSource

# AI Monitor の `共通.schema.yaml` の `decision` の `pattern` と同じ
DECISION_ID = re.compile(r"^[A-Z]+-[0-9]+$")
DECISION_DOCS_DIR = ".mindstella/docs"


def find_decisions(source: ServedSource) -> dict[str, Path]:
    """`decisions.folders` のうち、ちょうど 1 つのフォルダに文書がある検討事項の ID と文書のパスを返す。"""
    # 相対パスはメインのリポジトリの直下から数える（ワークツリーから配信していても `tmp/` はメインにある）
    base = source.main_root or source.repo_root or source.root
    found: dict[str, Path] = {}
    counts: Counter[str] = Counter()
    for folder in source.config.decision_folders:
        docs = (base / folder) / DECISION_DOCS_DIR
        # 無いフォルダは検討事項を持たないものとして飛ばす
        if not docs.is_dir():
            continue
        for file in sorted(docs.glob("*.md")):
            if file.is_file() and DECISION_ID.fullmatch(file.stem):
                counts[file.stem] += 1
                found.setdefault(file.stem, file)
    # 2 つ以上のフォルダにある ID は、どの検討事項か決まらないため除く
    return {decision: path for decision, path in found.items() if counts[decision] == 1}

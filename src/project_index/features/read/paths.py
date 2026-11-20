"""読み取り API が読む場所。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.access.types import Target
from project_index.features.history.query import resolve_ref

if TYPE_CHECKING:
    from project_index.features.history.types import ResolvedRef
    from project_index.features.sources.registry import SourceRegistry


def read_target(
    source_id: str, ref: str | None, *, registry: SourceRegistry
) -> tuple[Target, ResolvedRef | None]:
    """読み取り API のパスの配信元とリビジョンから読む場所を作る。"""
    source = registry.get(source_id)
    # 読み取り API は 127.0.0.1 だけで待ち受けるので、作業場所の権限は見ない
    if not source.is_git or source.repo_root is None:
        return Target(source, source.root, None, None, "read"), None
    default_ref = source.config.default_ref
    name = ref or default_ref
    resolved = resolve_ref(source.repo_root, name, date_base=default_ref)
    # `ref` は応答に出すリビジョンの名前、`commit` は 1 回だけ解いた commit
    target = Target(source, source.root, name, None, "read", commit=resolved.commit)
    return target, resolved

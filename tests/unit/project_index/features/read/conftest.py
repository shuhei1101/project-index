from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from project_index.features.convert.service import ConvertService
from project_index.features.documents.store import DocumentStore
from project_index.features.history.snapshot import SnapshotStore
from project_index.features.sources.types import DocumentTable, ScriptEntry, ServedSource


@pytest.fixture
def make_view_env(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., Any],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., Any],
    make_handlers: Callable[..., Any],
) -> Callable[..., SimpleNamespace]:
    """文書を置いた配信元 sample と、実物の部品を束ねた配線済みの関数を作る関数を返す。

    返す値は handlers（配線済みの関数）・source（配信元）・root（配信元のフォルダ）を持つ。
    """

    def _make(
        files: dict[str, str] | None = None,
        *,
        root: Path | None = None,
        converters: list[ScriptEntry] | None = None,
        converter_timeout: float = 10,
        tables: list[DocumentTable] | None = None,
        nav: dict[str, Any] | None = None,
        extra_sources: list[ServedSource] | None = None,
        decision_folders: list[str] | None = None,
        **source_overrides: Any,
    ) -> SimpleNamespace:
        if root is None:
            root = tmp_path / "sample"
            default_files = {"docs/a.yaml": "id: a\nname: A\n", "docs/b.yaml": "id: b\nname: B\n"}
            write_files(root, files or default_files)
        row = DocumentTable(
            id="rules",
            paths=["docs/*.yaml"],
            schema_path="schemas/rule.schema.yaml",
            converter="c" if converters else None,
        )
        config = make_source_config(
            documents=tables or [row],
            converters=converters or [],
            nav=nav,
            decision_folders=decision_folders or [],
        )
        source = make_served_source(id="sample", root=root, config=config, **source_overrides)
        store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
        handlers = make_handlers(
            registry=make_registry(source, *(extra_sources or [])),
            store=store,
            snapshots=store.snapshots,
            converter=ConvertService(tmp_path / "converted", store, converter_timeout),
        )
        return SimpleNamespace(handlers=handlers, source=source, root=root)

    return _make

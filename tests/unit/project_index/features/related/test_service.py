from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.documents.store import DocumentStore
from project_index.features.history.snapshot import SnapshotStore
from project_index.features.related.service import trace_related
from project_index.features.related.types import RelatedRequest, RelatedResult
from project_index.features.seen.store import SeenStore
from project_index.features.seen.types import SEEN_MARK
from project_index.features.sources.registry import SourceRegistry
from project_index.features.sources.types import DocumentTable, ServedSource, SourceConfig
from project_index.shared.errors import DocumentNotFoundError, InvalidArgumentError

if TYPE_CHECKING:
    from collections.abc import Callable


CHAIN = {
    "docs/doc-1.yaml": "id: doc-1\nname: 文書 1\nrelated:\n  - to: doc-2\n    type: references\n",
    "docs/doc-2.yaml": "id: doc-2\nname: 文書 2\nrelated:\n  - to: doc-3\n    type: references\n",
    "docs/doc-3.yaml": "id: doc-3\nname: 文書 3\n",
}


@dataclass
class RelatedEnv:
    """関連のたどりに渡す部品と、配信元のフォルダ。"""

    registry: SourceRegistry
    store: DocumentStore
    seen: SeenStore
    root: Path

    def trace(self, **request: Any) -> RelatedResult:
        return trace_related(
            RelatedRequest(cwd=str(self.root), **request),
            registry=self.registry,
            store=self.store,
            seen=self.seen,
        )


@pytest.fixture
def make_env(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> Callable[..., RelatedEnv]:
    """文書のファイルを置いた配信元 sample と、関連のたどりに渡す部品を作る関数を返す。"""

    def _make(files: dict[str, str], tables: list[DocumentTable] | None = None) -> RelatedEnv:
        root = tmp_path / "sample"
        write_files(root, files)
        rows = tables or [
            DocumentTable(id="rules", paths=["docs/*.yaml"], schema_path="schemas/rule.schema.yaml")
        ]
        source = make_served_source(
            id="sample", root=root, config=make_source_config(documents=rows)
        )
        return RelatedEnv(
            registry=make_registry(source),
            store=DocumentStore(SnapshotStore(tmp_path / "snapshots")),
            seen=SeenStore(tmp_path / "seen.sqlite3", retention_days=7),
            root=root,
        )

    return _make


def test_trace_related(make_env: Callable[..., RelatedEnv]) -> None:
    """起点からたどる（正常系）。"""
    # 準備
    env = make_env(CHAIN)
    # 実行
    result = env.trace(from_ids=["doc-1"])
    # 検証
    assert [(item.id, item.depth) for item in result.items] == [("doc-2", 1), ("doc-3", 2)]
    assert result.items[0].via_from == "doc-1"
    assert [(item.path, item.scope) for item in result.items] == [
        (str(env.root / "docs" / "doc-2.yaml"), "summary"),
        (str(env.root / "docs" / "doc-3.yaml"), "summary"),
    ]


def test_trace_related_when_code_paths(make_env: Callable[..., RelatedEnv]) -> None:
    """コードのパスから（正常系）。"""
    # 準備
    files = {
        "src/files.yaml": (
            "files:\n"
            "  - path: a.py\n"
            "    related:\n"
            "      - to: src/b.py\n"
            "        type: references\n"
            "  - path: b.py\n"
        ),
        "src/a.py": "a = 1\n",
        "src/b.py": "b = 2\n",
    }
    table = DocumentTable(
        id="src",
        paths=["src/files.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="files",
        body_file="path",
    )
    env = make_env(files, [table])
    # 実行
    result = env.trace(code_paths=["src/a.py"])
    # 検証
    assert [item.id for item in result.items] == ["src/b.py"]


def test_trace_related_when_seen(make_env: Callable[..., RelatedEnv]) -> None:
    """返却済みの相手（正常系）。"""
    # 準備
    env = make_env(CHAIN)
    # 実行
    first = env.trace(from_ids=["doc-1"], session_id="s1")
    second = env.trace(from_ids=["doc-1"], session_id="s1")
    third = env.trace(from_ids=["doc-1"], session_id="s1", repeat_seen=True)
    # 検証
    assert first.items[0].name == "文書 2"
    assert second.items[0].name == SEEN_MARK
    assert second.items[0].description == SEEN_MARK
    assert second.items[0].path is None
    assert second.items[0].scope is None
    assert third.items[0].name == "文書 2"


def test_trace_related_when_depth_over(make_env: Callable[..., RelatedEnv]) -> None:
    """深さの丸め（正常系）。"""
    # 準備
    env = make_env(CHAIN)
    # 実行
    result = env.trace(from_ids=["doc-1"], depth=5)
    # 検証
    assert any("4" in note for note in result.notes)


def test_trace_related_when_both_given(make_env: Callable[..., RelatedEnv]) -> None:
    """起点の指定の誤り（異常系）。"""
    # 準備
    env = make_env(CHAIN)
    # 実行・検証
    with pytest.raises(InvalidArgumentError):
        env.trace(from_ids=["doc-1"], code_paths=["src/a.py"])


def test_trace_related_when_missing(make_env: Callable[..., RelatedEnv]) -> None:
    """無い起点（異常系）。"""
    # 準備
    env = make_env(CHAIN)
    # 実行・検証
    with pytest.raises(DocumentNotFoundError) as exc_info:
        env.trace(from_ids=["doc-9"])
    assert exc_info.value.candidates["doc-9"]


def test_render_related_markdown_when_outside_scope() -> None:
    """作業範囲の外の表示（正常系）。"""
    from project_index.features.related.render import render_related_markdown

    # 準備
    result = RelatedResult(start=["doc-1"], outside_scope=True)
    # 実行
    markdown = render_related_markdown(result)
    # 検証
    lines = markdown.splitlines()
    assert lines[0] == "作業範囲の外（参考）"
    assert lines[1] == "doc-1 から 0 件"

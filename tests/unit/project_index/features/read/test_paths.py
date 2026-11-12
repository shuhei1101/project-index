from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.access.types import Target
from project_index.features.read.paths import find_page, page_path, read_target

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.documents.types import Document
    from project_index.features.sources.registry import SourceRegistry
    from project_index.features.sources.types import ServedSource, SourceConfig


def test_page_path(make_document: Callable[..., Document]) -> None:
    """ファイルと records（正常系）。"""
    # 準備
    plain = make_document(id="a", path="docs/a.yaml")
    record = make_document(id="r-1", path="docs/rules.yaml", record_index=0)
    # 実行
    plain_result = page_path(plain)
    record_result = page_path(record)
    # 検証
    assert plain_result == "docs/a"
    assert record_result == "docs/rules/r-1"


def test_find_page(make_document: Callable[..., Document]) -> None:
    """文書のページのパスで当たる（正常系）。"""
    # 準備
    document = make_document(id="a", path="rules/a.yaml")
    other = make_document(id="b", path="rules/b.yaml")
    # 実行
    result = find_page([other, document], "rules/a")
    # 検証
    assert result is document


def test_find_page_when_body_path(make_document: Callable[..., Document]) -> None:
    """本文のファイルのパスで当たる（正常系）。"""
    # 準備
    plain = make_document(id="a", path="rules/a.yaml")
    record = make_document(
        id="notes/b", path="notes/files.yaml", record_index=0, body_path="notes/b.md"
    )
    # 実行
    result = find_page([plain, record], "notes/b.md")
    # 検証
    assert result is record


def test_find_page_when_missing(make_document: Callable[..., Document]) -> None:
    """どれにも当たらない（正常系）。"""
    # 準備
    plain = make_document(id="a", path="rules/a.yaml")
    record = make_document(
        id="notes/b", path="notes/files.yaml", record_index=0, body_path="notes/b.md"
    )
    # 実行
    result = find_page([plain, record], "no/such")
    # 検証
    assert result is None


def test_find_page_when_doc_id(make_document: Callable[..., Document]) -> None:
    """文書の ID で行の文書を選ぶ（正常系）。"""
    # 準備
    first = make_document(id="term-1", path="terms.yaml", record_index=0)
    second = make_document(id="term-2", path="terms.yaml", record_index=1)
    # 実行
    chosen = find_page([first, second], "terms.yaml", doc_id="term-2")
    default = find_page([first, second], "terms.yaml")
    # 検証
    assert chosen is second
    assert default is first


def test_find_page_when_doc_id_missing(make_document: Callable[..., Document]) -> None:
    """文書の ID が一致しない（正常系）。"""
    # 準備
    first = make_document(id="term-1", path="terms.yaml", record_index=0)
    second = make_document(id="term-2", path="terms.yaml", record_index=1)
    # 実行
    unknown_id = find_page([first, second], "terms.yaml", doc_id="no-such")
    page = find_page([first, second], "terms/term-2", doc_id="term-2")
    # 検証
    assert unknown_id is None
    assert page is None


def test_read_target(
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """既定のリビジョン（正常系）。"""
    # 準備
    root = git_repo({"docs/a.yaml": "id: a\n"})
    source = make_served_source(
        id="sample",
        root=root,
        is_git=True,
        repo_root=root,
        config=make_source_config(default_ref="develop"),
    )
    commit = run_git(root, "rev-parse", "develop").strip()
    # 実行
    target, resolved = read_target("sample", None, registry=make_registry(source))
    # 検証
    assert isinstance(target, Target)
    assert target.ref == "develop"
    assert target.commit == commit
    assert resolved is not None
    assert resolved.commit == commit


def test_read_target_when_not_git(
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """Git 管理外（正常系）。"""
    # 準備
    source = make_served_source(id="notes", is_git=False)
    # 実行
    target, resolved = read_target("notes", "main", registry=make_registry(source))
    # 検証
    assert target.ref is None
    assert resolved is None

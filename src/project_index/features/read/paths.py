"""文書のページのパスと読む場所。"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from project_index.features.access.types import Target
from project_index.features.history.query import resolve_ref

if TYPE_CHECKING:
    from collections.abc import Sequence

    from project_index.features.documents.types import Document
    from project_index.features.history.types import ResolvedRef
    from project_index.features.sources.registry import SourceRegistry


def page_path(document: Document) -> str:
    """文書を URL のパスにする。"""
    path = PurePosixPath(document.path).with_suffix("").as_posix()
    if document.record_index is not None:
        return f"{path}/{document.id}"
    return path


def find_page(
    documents: Sequence[Document], page: str, *, doc_id: str | None = None
) -> Document | None:
    """文書のページのパスに当たる文書を探す。

    無ければ、文書のファイルか本文のファイルのパスが `page` と同じ最初の文書を返す
    （呼び出し側が本文の相対リンクを本文のファイルのパスで解決して渡すため）。
    `doc_id` を指したときは、文書のファイルか本文のファイルのパスが `page` と同じ文書から ID で選ぶ。
    """
    if doc_id is not None:
        return next(
            (
                document
                for document in documents
                if page in (document.path, document.body_path) and document.id == doc_id
            ),
            None,
        )
    found = next((document for document in documents if page_path(document) == page), None)
    if found is not None:
        return found
    return next(
        (document for document in documents if page in (document.path, document.body_path)),
        None,
    )


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

"""`trace_related` の処理。"""

from __future__ import annotations

import posixpath
from typing import TYPE_CHECKING, Literal

from project_index.features.access.service import resolve_read_targets
from project_index.features.documents.store import DocumentStore, not_found_error
from project_index.features.history.query import co_changed_files
from project_index.features.related.graph import walk_related
from project_index.features.related.suggest import suggest_related
from project_index.features.related.types import (
    DEPTH_MAX,
    RelatedItem,
    RelatedRequest,
    RelatedResult,
)
from project_index.features.seen.types import SEEN_MARK, SessionKey
from project_index.integrations.git import GitError
from project_index.shared.errors import (
    DocumentNotFoundError,
    InvalidArgumentError,
    ProjectIndexError,
    Violation,
)

if TYPE_CHECKING:
    from project_index.features.access.types import Target
    from project_index.features.documents.types import Document
    from project_index.features.seen.store import SeenStore
    from project_index.features.sources.registry import SourceRegistry


def _invalid(rule: str, path: str) -> InvalidArgumentError:
    """引数の違反 1 件の `InvalidArgumentError` を作る。"""
    return InvalidArgumentError(
        message=rule, violations=[Violation(path=path, rule=rule, fix=rule)]
    )


def _co_changed(target: Target, start: list[Document]) -> dict[str, int]:
    """起点のファイルと一緒に変わったファイルを、配信元の直下からのパスで返す（Git だけ）。"""
    source = target.source
    if not source.is_git or source.repo_root is None:
        return {}
    prefix = source.root.relative_to(source.repo_root).as_posix()
    paths = {document.body_path or document.path for document in start}
    repo_paths = [path if prefix == "." else f"{prefix}/{path}" for path in sorted(paths)]
    try:
        counts = co_changed_files(target.worktree or source.repo_root, repo_paths)
    except GitError:
        return {}
    if prefix == ".":
        return counts
    return {
        path.removeprefix(f"{prefix}/"): count
        for path, count in counts.items()
        if path.startswith(f"{prefix}/")
    }


def _depth(request: RelatedRequest, notes: list[str]) -> int:
    """引数の組み合わせを確かめ、たどる深さを上限に丸めて返す。"""
    if (request.from_ids is None) == (request.code_paths is None):
        msg = "from_ids か code_paths のどちらか 1 つを指定してください"
        raise _invalid(msg, "from_ids")
    if request.depth < 1:
        msg = "depth は 1 以上にしてください"
        raise _invalid(msg, "depth")
    if request.depth > DEPTH_MAX:
        notes.append(f"depth {request.depth} は上限 {DEPTH_MAX} に丸めました")
        return DEPTH_MAX
    return request.depth


def _start(
    request: RelatedRequest, target: Target, documents: dict[str, Document]
) -> list[Document]:
    """起点の文書を、文書の ID かコードのパスから引く（無ければ例外を送る）。"""
    if request.from_ids is not None:
        missing = [doc_id for doc_id in request.from_ids if doc_id not in documents]
        if missing:
            raise not_found_error(target.source.id, missing, list(documents))
        return [documents[doc_id] for doc_id in request.from_ids]
    return _start_by_paths(request.code_paths or [], documents)


def _start_by_paths(code_paths: list[str], documents: dict[str, Document]) -> list[Document]:
    """コードのパスを `body_path`（無ければ `path`）に持つ文書を起点にする。"""
    wanted = [posixpath.normpath(path).removeprefix("./") for path in code_paths]
    by_path = {document.body_path or document.path: document for document in documents.values()}
    missing = [path for path in wanted if path not in by_path]
    if missing:
        raise DocumentNotFoundError(
            message=f"文書がありません: {', '.join(missing)}",
            missing=missing,
            next_steps=["search_docs で body_path を確認してください"],
        )
    return [by_path[path] for path in wanted]


class _Others:
    """別の配信元の文書を、同じ作業場所の権限で引く（配信元ごとに 1 回だけ読む）。"""

    def __init__(
        self, request: RelatedRequest, registry: SourceRegistry, store: DocumentStore
    ) -> None:
        self._request = request
        self._registry = registry
        self._store = store
        self._cache: dict[str, dict[str, Document]] = {}
        self.targets: dict[str, Target] = {}

    def resolve(self, source_id: str, doc_id: str) -> Document | None:
        """別の配信元の文書を返す（読めない配信元・無い文書は `None`）。"""
        if source_id not in self._cache:
            try:
                other = resolve_read_targets(
                    registry=self._registry,
                    source=source_id,
                    cwd=self._request.cwd,
                    outside_scope=self._request.outside_scope,
                )[0]
                self._cache[source_id] = {d.id: d for d in self._store.load(other).documents}
                self.targets[source_id] = other
            except ProjectIndexError:
                self._cache[source_id] = {}
        return self._cache[source_id].get(doc_id)


type Found = tuple[Document, int, str, str, Literal["out", "in"]]


def _items(
    request: RelatedRequest,
    store: DocumentStore,
    target: Target,
    others: _Others,
    found: list[Found],
    seen_ids: dict[str, set[str]],
) -> tuple[list[RelatedItem], dict[str, list[Document]]]:
    """たどった文書を結果の項目にし、本文を返した文書を配信元ごとに集める。"""
    items: list[RelatedItem] = []
    returned: dict[str, list[Document]] = {}
    for document, level, via_from, via_type, via_direction in found:
        already = document.id in seen_ids.get(document.source_id, set())
        # 読んだ場所での絶対パス（`ref` を渡した呼び出し・返却済みの文書は持たない）
        read_target = (
            target
            if document.source_id == target.source.id
            else others.targets.get(document.source_id)
        )
        path = (
            store.location(read_target, document)
            if not already and request.ref is None and read_target is not None
            else None
        )
        items.append(
            RelatedItem(
                id=document.id,
                source=document.source_id if document.source_id != target.source.id else None,
                depth=level,
                via_from=via_from,
                via_type=via_type,
                via_direction=via_direction,
                name=SEEN_MARK if already else str(document.metadata.get("name", "")),
                description=SEEN_MARK if already else str(document.metadata.get("description", "")),
                path=path,
                scope="summary" if path else None,
            )
        )
        if not already:
            returned.setdefault(document.source_id, []).append(document)
    return items, returned


def _seen_ids(
    request: RelatedRequest, seen: SeenStore, key: SessionKey | None, found: list[Found]
) -> dict[str, set[str]]:
    """この会話で同じバージョンを返却済みの文書の ID を、配信元ごとに引く。"""
    if request.repeat_seen:
        return {}
    return {
        source_id: seen.returned(
            key,
            source_id,
            "related",
            {d.id: d.version for d, *_ in found if d.source_id == source_id},
        )
        for source_id in {document.source_id for document, *_ in found}
    }


def trace_related(
    request: RelatedRequest,
    *,
    registry: SourceRegistry,
    store: DocumentStore,
    seen: SeenStore,
) -> RelatedResult:
    """`trace_related` の要求を処理して関連のたどりの結果を返す。"""
    notes: list[str] = []
    depth = _depth(request, notes)
    target = resolve_read_targets(
        registry=registry,
        source=request.source,
        ref=request.ref,
        worktree=request.worktree,
        cwd=request.cwd,
        outside_scope=request.outside_scope,
    )[0]
    documents = {document.id: document for document in store.load(target).documents}
    start = _start(request, target, documents)
    others = _Others(request, registry, store)
    found, walk_notes = walk_related(
        start, documents, depth=depth, direction=request.direction, resolve_other=others.resolve
    )
    notes.extend(walk_notes)
    key = SessionKey.of(request.session_id, request.agent_id)
    items, returned = _items(
        request, store, target, others, found, _seen_ids(request, seen, key, found)
    )
    suggestions = []
    if request.suggest:
        exclude = {document.id for document in start} | {document.id for document, *_ in found}
        suggestions = suggest_related(
            start,
            list(documents.values()),
            exclude=exclude,
            co_changed=_co_changed(target, start),
            activity=seen.activity(key, target.source.id),
        )
    for source_id, docs in returned.items():
        seen.mark_returned(key, source_id, "related", docs)
    return RelatedResult(
        start=[document.id for document in start],
        items=items,
        suggestions=suggestions,
        notes=notes,
        outside_scope=target.outside_scope
        or any(
            others.targets[document.source_id].outside_scope
            for document, *_ in found
            if document.source_id in others.targets
        ),
    )

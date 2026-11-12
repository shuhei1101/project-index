"""`list_changes` の処理。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

from project_index.features.access.service import resolve_read_targets
from project_index.features.changes.compare import changed_keys, count_occurrences, diff_lines
from project_index.features.changes.types import (
    LAST_READ_LABEL,
    WORKTREE_LABEL,
    ChangeItem,
    ChangesRequest,
    ChangesResult,
    ContainsChange,
    ContainsQuery,
    RangePoint,
)
from project_index.features.documents.loader import documents_from_text
from project_index.features.documents.store import DocumentStore
from project_index.features.documents.types import Document
from project_index.features.history.query import (
    changed_files,
    list_commits,
    read_file_at,
    resolve_ref,
)
from project_index.features.history.types import FileChange, ResolvedRef
from project_index.features.search.cursor import decode_cursor, encode_cursor
from project_index.features.search.fields import known_fields
from project_index.features.search.filters import check_filter, compile_regex, match_filter
from project_index.features.search.types import LIMIT_MAX, MAX_CHARS_LIMIT, SearchRequest
from project_index.features.seen.types import SessionKey
from project_index.shared.errors import InvalidArgumentError, LastReadNotFoundError, Violation
from project_index.shared.hashing import value_hash
from project_index.shared.narrowing import is_dict
from project_index.shared.yaml_io import YamlLoadError, load_yaml

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from project_index.features.access.types import Target
    from project_index.features.seen.store import SeenStore
    from project_index.features.sources.registry import SourceRegistry
    from project_index.features.sources.types import DocumentTable

SHORT_COMMIT = 7
MULTI_SOURCE_MIN = 2
BODY = "body"


def _invalid(violations: list[Violation]) -> InvalidArgumentError:
    """引数の違反を `InvalidArgumentError` にする。"""
    return InvalidArgumentError(
        message=f"引数が正しくありません: {len(violations)} 件", violations=violations
    )


def _content(document: Document) -> dict[str, Any]:
    """比べる内容（`body_path` のある文書は `body` も 1 つのキーにする）。"""
    if document.body_path is None:
        return dict(document.data)
    return {**document.data, BODY: document.body}


def _index_files(store: DocumentStore, target: Target) -> dict[str, str]:
    """今の文書の `body_path` → 索引のファイル（`path`）を、`root` からのパスで集める。"""
    return {
        document.body_path: document.path
        for document in store.load(target).documents
        if document.body_path is not None
    }


def _file_reader(work_root: Path, prefix: str, commit: str | None) -> Callable[[str], str | None]:
    """`root` からのパスのファイルを、commit のリビジョン（無ければ作業ツリー）から読む関数を作る。"""

    def read(relative: str) -> str | None:
        git_path = relative if prefix == "." else f"{prefix}/{relative}"
        if commit is not None:
            return read_file_at(work_root, commit, git_path)
        current = work_root / git_path
        return current.read_text(encoding="utf-8") if current.is_file() else None

    return read


def _relative(path: str, prefix: str) -> str:
    """リポジトリの直下からのパスを、配信元の直下（`prefix`）からのパスにする。"""
    return path if prefix == "." else path.removeprefix(f"{prefix}/")


def _with_index_files(
    changes: list[FileChange], prefix: str, indexes: Mapping[str, str]
) -> list[FileChange]:
    """本文のファイルが変わったときは、それを指す索引のファイルも変わったものとして加える。"""
    result = list(changes)
    changed = {change.path for change in changes}
    for change in changes:
        index_path = indexes.get(_relative(change.path, prefix))
        if index_path is None:
            continue
        git_index = index_path if prefix == "." else f"{prefix}/{index_path}"
        if git_index not in changed:
            changed.add(git_index)
            result.append(FileChange(path=git_index, change="modified"))
    return result


def _documents_between(
    store: DocumentStore, target: Target, start_commit: str, end_commit: str | None
) -> tuple[dict[str, Document], dict[str, Document]]:
    """2 つの commit（終点が無ければ作業ツリー）の間の前と後の文書を、ID → 文書で作る。"""
    source = target.source
    repo_root = source.repo_root or source.root
    work_root = target.worktree or repo_root
    prefix = source.root.relative_to(repo_root).as_posix()
    changes = _with_index_files(
        changed_files(work_root, start_commit, end_commit), prefix, _index_files(store, target)
    )
    before: dict[str, Document] = {}
    after: dict[str, Document] = {}
    readers = (
        (_file_reader(work_root, prefix, start_commit), before),
        (_file_reader(work_root, prefix, end_commit), after),
    )
    for change in changes:
        # 配信元の外のファイルは見ない
        if prefix != "." and not change.path.startswith(f"{prefix}/"):
            continue
        relative = _relative(change.path, prefix)
        table = next(
            (row for row in source.config.documents if row.enabled and row.matches(relative)),
            None,
        )
        if table is None:
            continue
        for reader, bucket in readers:
            bucket.update(_read_documents(target, table, relative, reader))
    return before, after


def _read_documents(
    target: Target, table: DocumentTable, relative: str, reader: Callable[[str], str | None]
) -> dict[str, Document]:
    """1 つの端のファイルを読み、文書を ID → 文書で返す（無ければ空）。"""
    text = reader(relative)
    if text is None:
        return {}
    source = target.source
    # 本文のファイルも、索引のファイルと同じ端から読む
    documents, _ = documents_from_text(
        text, source.root, relative, table, source_id=source.id, read_body=reader
    )
    return {document.id: document for document in documents}


def _recorded_document(
    target: Target, table: DocumentTable, doc_id: str, content: str, current: dict[str, Document]
) -> Document | None:
    """前回読んだ内容（`body`）から、比べる前の文書を作る。"""
    source = target.source
    if table.records is None:
        found, _ = documents_from_text(
            content, target.base, f"{doc_id}.yaml", table, source_id=source.id
        )
        return found[0] if found else None
    now = current.get(doc_id)
    if now is None:
        # 今は無い文書は、記録の内容だけを本文にした文書にする
        return Document(
            id=doc_id,
            kind=table.id,
            source_id=source.id,
            path=doc_id,
            record_index=None,
            data={},
            body=content,
            body_path=None,
            metadata={"id": doc_id},
            version="",
            created=None,
            updated=None,
        )
    # 本文のファイルを持つ行は本文だけが変わる。持たない行の本文は要素を書き出した YAML
    data = now.data if table.body_file is not None else _element_data(content, now.data)
    return replace(now, data=data, body=content)


def _element_data(content: str, fallback: dict[str, Any]) -> dict[str, Any]:
    """要素を書き出した YAML を辞書に戻す（読めなければ今の内容）。"""
    try:
        value = load_yaml(content)
    except YamlLoadError:
        return fallback
    # YAML から読んだ辞書のキーは文字列として扱う
    return cast("dict[str, Any]", value) if is_dict(value) else fallback


def _range_documents(
    store: DocumentStore, target: Target, request: ChangesRequest
) -> tuple[dict[str, Document], dict[str, Document], RangePoint, RangePoint]:
    """区間の前と後の文書を、ID → 文書で作る。"""
    source = target.source
    repo_root = source.repo_root or source.root
    default_ref = source.config.default_ref
    if request.from_ is None:
        msg = "区間の始点がありません"
        raise RuntimeError(msg)
    start = resolve_ref(repo_root, request.from_, date_base=default_ref, argument="from")
    end = (
        resolve_ref(repo_root, request.to, date_base=default_ref, argument="to")
        if request.to is not None
        else None
    )
    before, after = _documents_between(store, target, start.commit, end.commit if end else None)
    from_point = RangePoint(request.from_, start.commit[:SHORT_COMMIT], start.date)
    to_point = (
        RangePoint(request.to or "", end.commit[:SHORT_COMMIT], end.date)
        if end is not None
        else RangePoint(WORKTREE_LABEL)
    )
    return before, after, from_point, to_point


def _word_change(
    before: dict[str, Document],
    after: dict[str, Document],
    query: ContainsQuery,
    from_point: RangePoint,
    to_point: RangePoint,
    found: dict[str, list[ContainsChange]],
    last_seen: dict[str, Document],
) -> None:
    """前と後の文書の語の出現数を比べ、違う文書へ区間の語の増減を足す。"""
    for doc_id in sorted({*before, *after}):
        old, new = before.get(doc_id), after.get(doc_id)
        count_before = count_occurrences(old.body, query) if old else 0
        count_after = count_occurrences(new.body, query) if new else 0
        judged = new or old
        if judged is None:
            msg = "比べる文書がありません"
            raise RuntimeError(msg)
        last_seen[doc_id] = judged
        if count_before != count_after:
            found.setdefault(doc_id, []).append(
                ContainsChange(
                    kind="added" if count_after > count_before else "removed",
                    from_=from_point,
                    to=to_point,
                    count_before=count_before,
                    count_after=count_after,
                )
            )


def _commit_point(commit: str, moment: datetime | None) -> RangePoint:
    """commit の端（`input` を空にして、commit（短縮）と日時を持つ）を作る。"""
    return RangePoint("", commit[:SHORT_COMMIT], moment)


def _word_changes_in_range(
    store: DocumentStore,
    target: Target,
    query: ContainsQuery,
    start: ResolvedRef,
    end: ResolvedRef | None,
) -> tuple[dict[str, list[ContainsChange]], dict[str, Document]]:
    """区間の commit ごとに、親との文書の語の出現数を比べる（マージ commit は見ない）。"""
    source = target.source
    work_root = target.worktree or source.repo_root or source.root
    found: dict[str, list[ContainsChange]] = {}
    last_seen: dict[str, Document] = {}
    steps = list_commits(work_root, start.commit, end.commit if end else "HEAD")
    for step in steps:
        before, after = _documents_between(store, target, step.parent, step.commit)
        _word_change(
            before,
            after,
            query,
            _commit_point(step.parent, step.parent_date),
            _commit_point(step.commit, step.date),
            found,
            last_seen,
        )
    if end is None:
        # 終点が作業ツリーのときは、最後に HEAD と作業ツリーの間も比べる
        head = resolve_ref(work_root, "HEAD", date_base=source.config.default_ref)
        before, after = _documents_between(store, target, head.commit, None)
        _word_change(
            before,
            after,
            query,
            _commit_point(head.commit, head.date),
            RangePoint(WORKTREE_LABEL),
            found,
            last_seen,
        )
    return found, last_seen


def _check_request(request: ChangesRequest) -> None:
    """`from` の無い `to` と、正規表現として読めない `contains.value` を違反にする。"""
    if request.to is not None and request.from_ is None:
        raise _invalid(
            [Violation(path="to", rule="to には from が要ります", fix="from も指定してください")]
        )
    query = request.contains
    if query is None or not query.regex:
        return
    try:
        compile_regex(query.value, case_sensitive=query.case_sensitive)
    except re.error as error:
        raise _invalid(
            [
                Violation(
                    path="contains.value",
                    rule=f"正規表現として読み込めません（{error}）",
                    fix="正規表現として正しい値にしてください",
                )
            ]
        ) from error


def _check_git(targets: list[Target]) -> None:
    """区間を指す呼び出しで、Git の管理外の配信元を違反にする。"""
    for target in targets:
        if not target.source.is_git:
            raise _invalid(
                [
                    Violation(
                        path="from",
                        rule=f"{target.source.id} は Git の管理外なので区間を指せません",
                        fix="from を省くと、この会話で前回読んだ時点からの変更を返却します",
                    )
                ]
            )


@dataclass
class _Sides:
    """配信元 1 つの、比べる前と後の文書・区間の端・語の増減。"""

    before: dict[str, Document]
    after: dict[str, Document]
    from_point: RangePoint
    to_point: RangePoint
    word_changes: dict[str, list[ContainsChange]] = field(
        default_factory=dict[str, list[ContainsChange]]
    )
    word_documents: dict[str, Document] = field(default_factory=dict[str, Document])
    read_before: bool = False


def _range_sides(store: DocumentStore, target: Target, request: ChangesRequest) -> _Sides:
    """区間（`from`・`to`）の前と後の文書と、区間の commit ごとの語の増減を作る。"""
    before, after, from_point, to_point = _range_documents(store, target, request)
    sides = _Sides(before, after, from_point, to_point)
    query = request.contains
    if query is None or request.from_ is None:
        return sides
    source = target.source
    repo_root = source.repo_root or source.root
    default_ref = source.config.default_ref
    sides.word_changes, sides.word_documents = _word_changes_in_range(
        store,
        target,
        query,
        resolve_ref(repo_root, request.from_, date_base=default_ref, argument="from"),
        resolve_ref(repo_root, request.to, date_base=default_ref, argument="to")
        if request.to is not None
        else None,
    )
    return sides


def _last_read_sides(
    store: DocumentStore,
    seen: SeenStore,
    key: SessionKey | None,
    target: Target,
    request: ChangesRequest,
) -> _Sides:
    """この会話で前回読んだ内容と今の文書を、前と後の文書にする。"""
    source = target.source
    last = seen.last_read(key, source.id)
    current = {document.id: document for document in store.load(target).documents}
    before: dict[str, Document] = {}
    for doc_id, record in last.items():
        table = next((r for r in source.config.documents if r.id == record.doc_kind), None)
        if table is None:
            continue
        # 記録の文書の ID は、読んだときの ID に合わせる
        found = _recorded_document(target, table, doc_id, record.content, current)
        if found is not None:
            before[doc_id] = found
    after = {doc_id: current[doc_id] for doc_id in last if doc_id in current}
    earliest = min((record.read_at for record in last.values()), default=None)
    sides = _Sides(
        before,
        after,
        RangePoint(LAST_READ_LABEL, None, earliest),
        RangePoint(WORKTREE_LABEL),
        read_before=bool(last),
    )
    if request.contains is not None:
        # 前回読んだ時点から比べる呼び出しは、比べた区間全体を 1 つの区間にする
        _word_change(
            before,
            after,
            request.contains,
            sides.from_point,
            sides.to_point,
            sides.word_changes,
            sides.word_documents,
        )
    return sides


ChangeKind = Literal["added", "modified", "deleted", "unchanged"]


def _change_kind(
    old: Document | None, new: Document | None, changed: bool, *, contains: bool
) -> ChangeKind | None:
    """前後の文書の有無と変わったキーから変更の種類を決める（変更が無ければ `None`）。"""
    if old is None and new is None:
        # 区間の中で語が入って消え、両端に文書が無い
        return "unchanged"
    if old is None:
        return "added"
    if new is None:
        return "deleted"
    if changed:
        return "modified"
    # 語の増減で残した文書は、内容が変わらなくても返す
    return "unchanged" if contains else None


@dataclass(frozen=True)
class _ItemContext:
    """変更の項目を作るときに共通の要求・部品・配信元の数・使える項目。"""

    request: ChangesRequest
    store: DocumentStore
    multi_source: bool
    fields: dict[str, str]


def _change_items(
    context: _ItemContext, target: Target, sides: _Sides
) -> list[tuple[ChangeItem, Document]]:
    """配信元 1 つの前と後の文書を突き合わせ、変更の項目と条件の照合に使った文書を返す。"""
    request = context.request
    query = request.contains
    items: list[tuple[ChangeItem, Document]] = []
    for doc_id in sorted({*sides.before, *sides.after, *sides.word_changes}):
        # 語の増減を持たない文書は残さない
        if query is not None and doc_id not in sides.word_changes:
            continue
        old, new = sides.before.get(doc_id), sides.after.get(doc_id)
        values = changed_keys(
            _content(old) if old else {},
            _content(new) if new else {},
            ignore=target.source.config.diff_ignore_keys,
        )
        change = _change_kind(old, new, bool(values), contains=query is not None)
        if change is None:
            continue
        judged = new or old or sides.word_documents[doc_id]
        if not match_filter(
            request.filter,
            judged,
            fields=context.fields,
            today=datetime.now(UTC).astimezone().date(),
        ):
            continue
        items.append(
            (_change_item(context, target, sides, doc_id, change, values, (old, new)), judged)
        )
    return items


def _change_item(
    context: _ItemContext,
    target: Target,
    sides: _Sides,
    doc_id: str,
    change: ChangeKind,
    values: dict[str, tuple[Any, Any]],
    pair: tuple[Document | None, Document | None],
) -> ChangeItem:
    """変更の項目 1 件を作る（`to` が無ければ後の文書の場所を添える）。"""
    request = context.request
    old, new = pair
    diff = (
        diff_lines(old.body if old else "", new.body if new else "")
        if request.view == "full"
        else None
    )
    location = (
        context.store.location(target, new) if request.to is None and new is not None else None
    )
    return ChangeItem(
        id=doc_id,
        source=target.source.id if context.multi_source else None,
        change=change,
        keys=list(values),
        values=values,
        diff=diff,
        path=location,
        scope=(("section" if request.view == "full" else "summary") if location else None),
        contains_changes=sides.word_changes.get(doc_id) if request.contains is not None else None,
    )


def _bounded(request: ChangesRequest, notes: list[str]) -> tuple[int, int]:
    """`limit`・`max_chars` を上限に丸める（丸めたら注意書きを足す）。"""
    limit = request.limit
    if limit < 1:
        raise _invalid([Violation(path="limit", rule="1 以上にしてください")])
    if limit > LIMIT_MAX:
        limit = LIMIT_MAX
        notes.append(f"limit {request.limit} は上限 {LIMIT_MAX} に丸めました")
    max_chars = request.max_chars
    if max_chars > MAX_CHARS_LIMIT:
        max_chars = MAX_CHARS_LIMIT
        notes.append(f"max_chars {request.max_chars} は上限 {MAX_CHARS_LIMIT} に丸めました")
    return limit, max_chars


def _page(window: list[ChangeItem], max_chars: int) -> tuple[list[ChangeItem], bool]:
    """先頭から `max_chars` に収まる項目を返す（1 件目は収まらなくても返す）。"""
    items: list[ChangeItem] = []
    size = 0
    for item in window:
        item_size = len(item.id) + sum(len(key) for key in item.keys) + len(item.diff or "")
        if items and size + item_size > max_chars:
            return items, True
        items.append(item)
        size += item_size
    return items, False


def list_changes(
    request: ChangesRequest,
    *,
    registry: SourceRegistry,
    store: DocumentStore,
    seen: SeenStore,
) -> ChangesResult:
    """`list_changes` の要求を処理して変更の結果を返す。"""
    _check_request(request)
    targets = resolve_read_targets(
        registry=registry,
        source=request.source,
        worktree=request.worktree,
        cwd=request.cwd,
        outside_scope=request.outside_scope,
    )
    if request.from_ is not None:
        _check_git(targets)
    key = SessionKey.of(request.session_id, request.agent_id)
    notes: list[str] = []
    fields = known_fields(
        store.row_schema(target, table.id)
        for target in targets
        for table in target.source.config.documents
        if table.enabled
    )
    violations = check_filter(SearchRequest(filter=request.filter, order_by=[]), fields)
    if violations:
        raise _invalid(violations)
    context = _ItemContext(
        request=request,
        store=store,
        multi_source=len(targets) >= MULTI_SOURCE_MIN,
        fields=fields,
    )
    entries: list[tuple[int, ChangeItem]] = []
    points: list[tuple[RangePoint, RangePoint]] = []
    any_last_read = False
    for index, target in enumerate(targets):
        sides = (
            _range_sides(store, target, request)
            if request.from_ is not None
            else _last_read_sides(store, seen, key, target, request)
        )
        any_last_read = any_last_read or sides.read_before
        points.append((sides.from_point, sides.to_point))
        entries.extend((index, item) for item, _ in _change_items(context, target, sides))
    if request.from_ is None and not any_last_read:
        raise LastReadNotFoundError(
            message="この会話で参照した記録がありません。from を指定してください",
            next_steps=["from に commit やブランチを指定してください"],
        )
    entries.sort(key=lambda entry: (entry[0], entry[1].id))
    return _result(request, targets, points, [item for _, item in entries], notes)


def _result(
    request: ChangesRequest,
    targets: list[Target],
    points: list[tuple[RangePoint, RangePoint]],
    entries: list[ChangeItem],
    notes: list[str],
) -> ChangesResult:
    """並べた項目を続きの位置と `max_chars` で切り出し、変更の結果にする。"""
    limit, max_chars = _bounded(request, notes)
    fingerprint = value_hash(
        request.model_dump(mode="json", exclude={"cursor", "limit", "max_chars"}, by_alias=True)
    )
    start = decode_cursor(request.cursor, fingerprint) if request.cursor else 0
    items, truncated = _page(entries[start : start + limit], max_chars)
    next_position = start + len(items)
    next_cursor = (
        encode_cursor(next_position, fingerprint) if next_position < len(entries) else None
    )
    if truncated:
        notes.append(
            f"max_chars {max_chars} で打ち切りました。cursor を指定すると続きを取得できます"
        )
    # 複数の配信元を比べたときは、配信元ごとの区間を先頭に並べる
    if len(points) >= MULTI_SOURCE_MIN:
        for target, (from_point, to_point) in zip(targets, points, strict=True):
            notes.insert(
                0,
                f"{target.source.id}: {from_point.commit or from_point.input} → "
                f"{to_point.commit or to_point.input}",
            )
    return ChangesResult(
        range_from=points[0][0],
        range_to=points[0][1],
        total_count=len(entries),
        items=items,
        next_cursor=next_cursor,
        truncated=truncated,
        notes=notes,
        outside_scope=any(target.outside_scope for target in targets),
    )

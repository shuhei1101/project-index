"""`search_docs` の処理。"""

from __future__ import annotations

import dataclasses
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Literal

from project_index.features.access.service import resolve_read_targets
from project_index.features.access.types import Target
from project_index.features.documents.aliases import collect_aliases, term_ids
from project_index.features.documents.fields import is_markdown_body
from project_index.features.documents.store import DocumentStore
from project_index.features.documents.types import Document
from project_index.features.search.body_parts import join_ranges, select_ranges
from project_index.features.search.cursor import decode_cursor, encode_cursor
from project_index.features.search.fields import field_values, known_fields
from project_index.features.search.filters import check_filter, match_filter, normalize
from project_index.features.search.snippets import count_matches, find_snippets, split_lines
from project_index.features.search.types import (
    FIELD_CHARS_DEFAULT,
    FIELD_CHARS_FULL,
    LIMIT_MAX,
    MAX_CHARS_LIMIT,
    SUMMARY_FIELDS,
    BodyRange,
    Condition,
    Group,
    GroupCount,
    OrderKey,
    SearchItem,
    SearchRequest,
    SearchResult,
    Snippet,
)
from project_index.features.seen.types import SEEN_MARK, SessionKey
from project_index.shared.errors import InvalidArgumentError, Violation
from project_index.shared.hashing import value_hash

if TYPE_CHECKING:
    from collections.abc import Sequence

    from project_index.features.seen.store import SeenStore
    from project_index.features.sources.registry import SourceRegistry
    from project_index.features.validation.service import DocumentChecker

NONE_LABEL = "（なし）"
MULTI_SOURCE_MIN = 2
BODY = "body"
MATCHES = "@matches"
ARRAY_FIELDS = ("tags", "main_tags", "related", "aliases", "avoid", "@sections")
FINGERPRINT_EXCLUDED = {"cursor", "limit", "max_chars"}


@dataclass(frozen=True)
class _Hit:
    """条件に当たった文書と、読んだ場所。"""

    target: Target
    document: Document
    source_index: int
    # `@matches`（本文の条件に当たった本文の全文の行の数）。使わない呼び出しでは 0
    matches: int = 0


def _invalid(violations: list[Violation]) -> InvalidArgumentError:
    """引数の違反を `InvalidArgumentError` にする。"""
    return InvalidArgumentError(
        message=f"引数が正しくありません: {len(violations)} 件",
        violations=violations,
        next_steps=["describe(source, kind) でスキーマを確認してください"],
    )


def _body_conditions(node: Condition | Group | None) -> list[Condition]:
    """条件の木から、本文を探す条件（`body`・`*` の条件）を集める。"""
    if node is None:
        return []
    if isinstance(node, Group):
        return [
            condition
            for child in node.all_of or node.any_of or []
            for condition in _body_conditions(child)
        ]
    return [node] if node.field in (BODY, "*") else []


def _sort_value(hit: _Hit, field: str) -> float | str | None:
    """並べ替えに使う値（比べられる型にそろえる。値が無ければ `None`）。"""
    if field == MATCHES:
        return float(hit.matches)
    values = field_values(hit.document, field)
    if not values:
        return None
    value = values[0]
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp()
    if isinstance(value, bool | int | float):
        return float(value)
    return unicodedata.normalize("NFKC", str(value)).casefold()


def _order(hits: list[_Hit], request: SearchRequest) -> list[_Hit]:
    """`order_by` の順に並べる（値が無い文書は向きによらず末尾）。"""
    ordered = sorted(hits, key=lambda hit: (hit.source_index, hit.document.id))
    # 渡していないときは `id` の昇順
    keys = [OrderKey(field="id")] if request.order_by is None else request.order_by
    for key in reversed(keys):
        present = [hit for hit in ordered if _sort_value(hit, key.field) is not None]
        missing = [hit for hit in ordered if _sort_value(hit, key.field) is None]
        present.sort(
            key=lambda hit, field=key.field: (  # type: ignore[misc]
                isinstance(_sort_value(hit, field), str),
                _sort_value(hit, field),
            ),
            reverse=key.direction == "desc",
        )
        ordered = [*present, *missing]
    return ordered


def _id_ordered(ordered: list[_Hit], request: SearchRequest) -> list[_Hit]:
    """`order_by` が無く `filter` が `id` の `eq` の条件 1 つのときは、その `values` の順にする。"""
    condition = request.filter
    if (
        request.order_by is not None
        or not isinstance(condition, Condition)
        or condition.field != "id"
        or condition.op != "eq"
    ):
        return ordered
    position = {document_id: index for index, document_id in enumerate(condition.values)}
    return sorted(ordered, key=lambda hit: position.get(hit.document.id, len(position)))


def _groups(hits: Sequence[_Hit], field: str) -> list[GroupCount]:
    """正規化した値ごとの件数を、件数の降順・値の昇順で返す。"""
    # 正規化した値 → 元の表記 → その表記が付いた文書の番号
    spellings: dict[str, dict[str, set[int]]] = {}
    for number, hit in enumerate(hits):
        values = field_values(hit.document, field) or [NONE_LABEL]
        for value in dict.fromkeys(str(item) for item in values):
            spellings.setdefault(normalize(value), {}).setdefault(value, set()).add(number)
    groups: list[GroupCount] = []
    for per_spelling in spellings.values():
        # 付いた文書が最も多い表記で返す（同数なら値の昇順で先のもの）
        shown = min(per_spelling, key=lambda value: (-len(per_spelling[value]), value))
        # 1 つの文書に付いた表記違いの値は 1 件と数える
        documents = set[int]().union(*per_spelling.values())
        groups.append(GroupCount(value=shown, count=len(documents)))
    return sorted(groups, key=lambda group: (-group.count, group.value))


def _cut(value: object, limit: int) -> object:
    """長い文字列を末尾で切り、残りの文字数を添える。"""
    if isinstance(value, str) and len(value) > limit:
        return f"{value[:limit]}…（残り {len(value) - limit} 文字）"
    return value


def _field_value(document: Document, field: str) -> object:
    """項目の値を返す（配列の項目と複数の値は配列、無ければ `None`）。"""
    values = field_values(document, field)
    if not values:
        return None
    return values if len(values) > 1 or field in ARRAY_FIELDS else values[0]


def _field_names(request: SearchRequest, document: Document) -> list[str]:
    """文書ごとに返す項目の名前を決める。"""
    if request.view == "ids":
        names: list[str] = []
    elif request.view == "summary":
        names = list(SUMMARY_FIELDS)
    else:
        names = [
            *SUMMARY_FIELDS,
            BODY,
            *(key for key in document.metadata if key not in SUMMARY_FIELDS),
        ]
    names.extend(name for name in request.fields if name not in names)
    return [name for name in names if name not in request.exclude_fields and name != "id"]


def _scope(
    document: Document,
    values: dict[str, Any],
    snippets: list[Snippet],
    field_chars: int,
    *,
    ranged: bool,
) -> Literal["full", "section", "summary"]:
    """返した範囲を決める（本文を切らずに返したら `full`）。"""
    if snippets or ranged:
        return "section"
    if not isinstance(values.get(BODY), str):
        return "summary"
    cut = len(document.body) > field_chars
    if cut or (document.record_index is not None and document.body_path is None):
        return "section"
    return "full"


def _item_size(item: SearchItem) -> int:
    """結果の文字数に数える項目の長さ。"""
    return (
        len(item.id)
        + sum(len(str(value)) for value in item.values.values())
        + sum(
            len(f"{line.line}:{line.text}") for snippet in item.snippets for line in snippet.lines
        )
    )


def _cut_body(
    document: Document, request: SearchRequest, notes: list[str]
) -> tuple[str, list[BodyRange], int]:
    """sections・lines で本文を切り出し、本文・範囲・本文の全体の行数を返す。"""
    lines = split_lines(document.body)
    # Markdown の本文でない文書には sections を渡さず、空の範囲にする
    plain_document = not is_markdown_body(document)
    ranges = select_ranges(
        lines,
        sections=None if plain_document else request.sections,
        line_range=request.lines,
    )
    if request.sections is not None and not ranges:
        if plain_document:
            notes.append(
                f"{document.id}: YAML の文書は sections で切り出せません。lines を使用してください"
            )
        else:
            notes.append(
                f"{document.id}: sections に該当する見出しがありません"
                f"（{', '.join(request.sections)}）"
            )
    return join_ranges(lines, ranges), ranges, len(lines)


def _load_targets(
    request: SearchRequest, store: DocumentStore, targets: list[Target], notes: list[str]
) -> tuple[list[tuple[int, Target, list[Document]]], list[dict[str, Any]]]:
    """読む場所ごとに文書を読み（`term` があれば語の指す文書に絞る）、使える項目のスキーマを集める。"""
    loaded: list[tuple[int, Target, list[Document]]] = []
    schemas: list[dict[str, Any]] = []
    for index, target in enumerate(targets):
        result = store.load(target)
        notes.extend(
            f"{problem.path} を読み込めないので除きました（{problem.detail}）"
            for problem in result.problems
        )
        documents = result.documents
        if request.term is not None:
            collection = collect_aliases(target.source, documents)
            if not collection.has_alias_rows:
                notes.append(
                    f"{target.source.id}: alias_type を持つ documents の行が無いので"
                    " term に該当する文書はありません"
                )
            ids = term_ids(collection.entries, request.term)
            documents = [document for document in documents if document.id in ids]
        loaded.append((index, target, documents))
        schemas.extend(
            store.row_schema(target, table.id)
            for table in target.source.config.documents
            if table.enabled
        )
    return loaded, schemas


def _bounded(request: SearchRequest, notes: list[str]) -> tuple[int, int]:
    """`limit`・`max_chars` を上限に丸める（丸めたら注意書きを足す）。"""
    if request.limit < 1:
        raise _invalid([Violation(path="limit", rule="1 以上にしてください")])
    limit = request.limit
    if limit > LIMIT_MAX:
        limit = LIMIT_MAX
        notes.append(f"limit {request.limit} は上限 {LIMIT_MAX} に丸めました")
    max_chars = request.max_chars
    if max_chars > MAX_CHARS_LIMIT:
        max_chars = MAX_CHARS_LIMIT
        notes.append(f"max_chars {request.max_chars} は上限 {MAX_CHARS_LIMIT} に丸めました")
    return limit, max_chars


def _per_source(targets: list[Target], hits: list[_Hit]) -> dict[str, int]:
    """配信元ごとの当たった件数（0 件の配信元は除く）。"""
    counts = {target.source.id: 0 for target in targets}
    for hit in hits:
        counts[hit.target.source.id] += 1
    return {name: count for name, count in counts.items() if count}


@dataclass(frozen=True)
class _Build:
    """結果の項目を作るときに共通の要求と、本文の返し方。"""

    request: SearchRequest
    store: DocumentStore
    multi: bool
    field_chars: int
    cuts_body: bool
    body_conditions: list[Condition]
    seen_ids: dict[str, set[str]]


@dataclass
class _Item:
    """文書 1 件の、返す値・抜粋・切り出した範囲・注意書き。"""

    values: dict[str, Any] = field(default_factory=dict[str, Any])
    snippets: list[Snippet] = field(default_factory=list[Snippet])
    ranges: list[BodyRange] | None = None
    total_lines: int | None = None
    notes: list[str] = field(default_factory=list[str])


def _put_body(build: _Build, hit: _Hit, item: _Item) -> None:
    """本文を返す（切り出し・抜粋・返し済みの印・文字数の切り詰め）。"""
    request = build.request
    document = hit.document
    body = document.body
    if build.cuts_body:
        body, item.ranges, item.total_lines = _cut_body(document, request, item.notes)
    if request.snippets is not None:
        context = request.snippets.context_lines
        before, after = request.snippets.before, request.snippets.after
        item.snippets = find_snippets(
            document.body,
            build.body_conditions,
            # 省いた前後の行数は context_lines にする
            before=context if before is None else before,
            after=context if after is None else after,
            max_count=request.snippets.max_per_doc,
            ranges=item.ranges,
        )
        return
    if document.id in build.seen_ids.get(hit.target.source.id, set()):
        item.values[BODY] = SEEN_MARK
        return
    # 切り出した本文は、切り出した後に文字数で切る
    item.values[BODY] = _cut(body, build.field_chars)


def _search_item(build: _Build, hit: _Hit) -> tuple[SearchItem, list[str]]:
    """当たった文書 1 件を、結果の項目と注意書きにする。"""
    request = build.request
    document = hit.document
    item = _Item()
    for name in _field_names(request, document):
        if name == MATCHES:
            item.values[name] = hit.matches
        elif name == BODY:
            _put_body(build, hit, item)
        else:
            item.values[name] = _cut(_field_value(document, name), build.field_chars)
    located = (
        request.view in ("summary", "full")
        and request.ref is None
        and item.values.get(BODY) != SEEN_MARK
    )
    scope = (
        _scope(
            document, item.values, item.snippets, build.field_chars, ranged=item.ranges is not None
        )
        if located
        else None
    )
    return (
        SearchItem(
            id=document.id,
            source=hit.target.source.id if build.multi else None,
            values=item.values,
            snippets=item.snippets,
            path=build.store.location(hit.target, document) if located else None,
            scope=scope,
            ranges=item.ranges,
            total_lines=item.total_lines,
        ),
        item.notes,
    )


@dataclass
class _Page:
    """`max_chars` に収めた項目と、返した文書・本文を返した文書。"""

    items: list[SearchItem] = field(default_factory=list[SearchItem])
    used: list[_Hit] = field(default_factory=list[_Hit])
    returned_bodies: list[_Hit] = field(default_factory=list[_Hit])
    truncated: bool = False


def _page(build: _Build, window: list[_Hit], max_chars: int, notes: list[str]) -> _Page:
    """先頭から `max_chars` に収まる項目を作る（1 件目は収まらなくても返す）。"""
    page = _Page()
    size = 0
    for hit in window:
        item, item_notes = _search_item(build, hit)
        item_size = _item_size(item)
        if page.items and size + item_size > max_chars:
            page.truncated = True
            break
        page.items.append(item)
        notes.extend(item_notes)
        page.used.append(hit)
        size += item_size
        if BODY in item.values and item.values[BODY] != SEEN_MARK:
            page.returned_bodies.append(hit)
    return page


def _seen_ids(
    request: SearchRequest,
    seen: SeenStore,
    key: SessionKey | None,
    targets: list[Target],
    window: list[_Hit],
) -> dict[str, set[str]]:
    """この会話で同じバージョンの本文を返し済みの文書の ID を、配信元ごとに引く。"""
    returns_body = request.view == "full" or BODY in request.fields
    cuts_body = request.sections is not None or request.lines is not None
    if not returns_body or request.repeat_seen or request.snippets is not None or cuts_body:
        return {}
    seen_ids: dict[str, set[str]] = {}
    for target in targets:
        versions = {
            hit.document.id: hit.document.version
            for hit in window
            if hit.target.source.id == target.source.id
        }
        seen_ids[target.source.id] = seen.returned(key, target.source.id, "body", versions)
    return seen_ids


def _hits(
    request: SearchRequest,
    loaded: list[tuple[int, Target, list[Document]]],
    body_conditions: list[Condition],
    fields: dict[str, str],
    today: date,
) -> list[_Hit]:
    """条件に当たる文書を集める（`@matches` を使う呼び出しは本文の当たった行を数える）。"""
    counts_matches = MATCHES in request.fields or any(
        key.field == MATCHES for key in request.order_by or []
    )
    return [
        _Hit(
            target,
            document,
            index,
            count_matches(document.body, body_conditions) if counts_matches else 0,
        )
        for index, target, documents in loaded
        for document in documents
        if match_filter(request.filter, document, fields=fields, today=today)
    ]


def search_docs(
    request: SearchRequest,
    *,
    registry: SourceRegistry,
    store: DocumentStore,
    checker: DocumentChecker,
    seen: SeenStore,
    today: date | None = None,
) -> SearchResult:
    """`search_docs` の要求を処理して検索の結果を返す。"""
    today = today or datetime.now(UTC).astimezone().date()
    notes: list[str] = []
    targets = resolve_read_targets(
        registry=registry,
        source=request.source,
        ref=request.ref,
        worktree=request.worktree,
        cwd=request.cwd,
        outside_scope=request.outside_scope,
    )
    outside_scope = any(target.outside_scope for target in targets)
    loaded, schemas = _load_targets(request, store, targets, notes)
    fields = known_fields(schemas)
    violations = check_filter(request, fields)
    if violations:
        raise _invalid(violations)
    limit, max_chars = _bounded(request, notes)
    body_conditions = _body_conditions(request.filter)
    hits = _hits(request, loaded, body_conditions, fields, today)
    multi = len(targets) >= MULTI_SOURCE_MIN
    result = SearchResult(
        total_count=len(hits),
        returned=0,
        view=request.view,
        per_source=_per_source(targets, hits) if multi else {},
        notes=notes,
        groups=_groups(hits, request.group_by) if request.group_by else [],
        source_label=",".join(target.source.id for target in targets),
        outside_scope=outside_scope,
    )
    if request.view == "count":
        return result
    ordered = _id_ordered(_order(hits, request), request)
    fingerprint = value_hash(request.model_dump(mode="json", exclude=FINGERPRINT_EXCLUDED))
    base = request.skip + (decode_cursor(request.cursor, fingerprint) if request.cursor else 0)
    window = ordered[base : base + limit]
    key = SessionKey.of(request.session_id, request.agent_id)
    build = _Build(
        request=request,
        store=store,
        multi=multi,
        field_chars=request.max_chars_per_field
        or (FIELD_CHARS_FULL if request.view == "full" else FIELD_CHARS_DEFAULT),
        cuts_body=request.sections is not None or request.lines is not None,
        body_conditions=body_conditions,
        seen_ids=_seen_ids(request, seen, key, targets, window),
    )
    page = _page(build, window, max_chars, notes)
    for hit in page.used:
        notes.extend(
            f"{hit.document.id}: {violation.rule}（{violation.path}）"
            for violation in checker.check(hit.target, hit.document, on="read")
        )
    next_position = base + len(page.items)
    has_rest = next_position < len(ordered) and (
        page.truncated or len(window) == limit or len(page.items) < len(window)
    )
    if page.truncated:
        notes.append(
            f"max_chars {max_chars} で打ち切りました。cursor を指定して続きを取得するか、"
            "fields を絞るか view: ids で再取得してください"
        )
    # sections・lines の呼び出しは返し済みに記録しない
    if not build.cuts_body:
        _mark_returned(seen, key, targets, page.returned_bodies)
    return dataclasses.replace(
        result,
        returned=len(page.items),
        next_cursor=encode_cursor(next_position - request.skip, fingerprint) if has_rest else None,
        truncated=page.truncated,
        items=page.items,
    )


def _mark_returned(
    seen: SeenStore, key: SessionKey | None, targets: list[Target], returned: list[_Hit]
) -> None:
    """本文を返した文書を、配信元ごとに返し済みとして記録する。"""
    for target in targets:
        documents = [hit.document for hit in returned if hit.target.source.id == target.source.id]
        seen.mark_returned(key, target.source.id, "body", documents)

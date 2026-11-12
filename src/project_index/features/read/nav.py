"""`nav` の `auto` の当たる文書の数・`filter` の検証・警告。"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from project_index.features.access.types import Target
from project_index.features.read.paths import page_path
from project_index.features.read.types import NavAutoCount
from project_index.features.search.fields import known_fields
from project_index.features.search.filters import check_filter, match_filter
from project_index.features.search.types import Condition, Group, SearchRequest
from project_index.shared.errors import Violation

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Mapping, Sequence

    from project_index.features.documents.store import DocumentStore
    from project_index.features.documents.types import Document
    from project_index.features.sources.types import ServedSource

logger = logging.getLogger(__name__)


def _filter_of(spec: Mapping[str, Any]) -> Condition | Group | None:
    """`auto.filter` を条件の木にする（読めない条件は `ValidationError`）。"""
    raw = spec.get("filter")
    return None if raw is None else SearchRequest(filter=raw).filter


def _select(
    documents: Sequence[Document],
    spec: Mapping[str, Any],
    *,
    fields: Mapping[str, str],
    today: date,
) -> list[Document]:
    """`auto` の `document` と `filter` に当たる文書を、文書のページのパスの昇順で返す。"""
    kind = spec.get("document")
    found = sorted((d for d in documents if kind is None or d.kind == str(kind)), key=page_path)
    try:
        node = _filter_of(spec)
    except ValidationError:
        return []
    if node is None:
        return found
    return [d for d in found if match_filter(node, d, fields=fields, today=today)]


def _walk_autos(
    items: Sequence[Mapping[str, Any]], path: str
) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """`items[]` を `group` の入れ子までたどり、`auto` のキーのパスと値を返す。"""
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        if "group" in item:
            yield from _walk_autos(item.get("items") or [], f"{item_path}.items")
        elif "auto" in item:
            yield f"{item_path}.auto", item["auto"]


def _autos(nav: Mapping[str, Any]) -> Iterator[tuple[str, str, Mapping[str, Any]]]:
    """`nav` を上からたどり、`auto` ごとのキーのパス・タブの名前・値を返す。"""
    for index, tab in enumerate(nav.get("tabs") or []):
        for path, spec in _walk_autos(tab.get("items") or [], f"nav.tabs[{index}].items"):
            yield path, str(tab.get("title", "")), spec


def nav_auto_counts(
    nav: Mapping[str, Any],
    documents: Sequence[Document],
    *,
    fields: Mapping[str, str],
    today: date,
) -> list[NavAutoCount]:
    """`nav` の全ての `auto` について、条件に当たる文書を数える。"""
    return [
        NavAutoCount(
            path=path,
            tab=tab,
            filter=spec.get("filter"),
            count=len(_select(documents, spec, fields=fields, today=today)),
        )
        for path, tab, spec in _autos(nav)
    ]


def check_nav_filters(
    nav: Mapping[str, Any], *, table_ids: Collection[str], fields: Mapping[str, str]
) -> list[Violation]:
    """`nav` の `auto` の `document` と `filter` が使えるかを確かめる。"""
    violations: list[Violation] = []
    for path, _, spec in _autos(nav):
        document = spec.get("document")
        if document is not None and str(document) not in table_ids:
            violations.append(Violation(path=f"{path}.document", rule="存在しない ID"))
        if spec.get("filter") is None:
            continue
        try:
            request = SearchRequest(filter=spec["filter"])
        except ValidationError as error:
            violations.append(
                Violation(path=f"{path}.filter", rule=f"条件として読み込めません（{error}）")
            )
            continue
        violations.extend(
            Violation(
                path=f"{path}.{violation.path}" if violation.path.startswith("filter") else path,
                rule=violation.rule,
                fix=violation.fix,
            )
            for violation in check_filter(request, fields)
        )
    return violations


def nav_warnings(
    store: DocumentStore, source: ServedSource, *, today: date | None = None
) -> list[Violation]:
    """配信元のクローン本体の文書で、使えない条件とどの文書にも当たらない条件を警告にする。"""
    nav = source.config.nav
    if not nav:
        return []
    today = today or date.today()  # noqa: DTZ011
    target = Target(source, source.root, None, None, "read")
    documents = store.load(target).documents
    fields = known_fields(
        store.row_schema(target, row.id) for row in source.config.documents if row.enabled
    )
    table_ids = [row.id for row in source.config.documents if row.enabled]
    counts = nav_auto_counts(nav, documents, fields=fields, today=today)
    return [
        *check_nav_filters(nav, table_ids=table_ids, fields=fields),
        *zero_count_warnings(counts),
    ]


def zero_count_warnings(counts: Sequence[NavAutoCount]) -> list[Violation]:
    """`count` が 0 の `auto` を警告にする。"""
    return [
        Violation(
            path=f"{count.path}.filter" if count.filter is not None else count.path,
            rule=(
                f"{count.tab}: 条件 {json.dumps(count.filter, ensure_ascii=False)}"
                " に該当する文書がありません"
            ),
        )
        for count in counts
        if not count.count
    ]

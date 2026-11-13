"""`write_docs`・`delete_docs` の処理。"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ruamel.yaml.comments import CommentedMap

from project_index.features.access.service import resolve_write_target
from project_index.features.access.types import Target
from project_index.features.changes.compare import diff_lines
from project_index.features.documents.fields import get_field, resolve_metadata, set_field
from project_index.features.documents.loader import documents_from_text
from project_index.features.documents.store import DocumentStore, not_found_error
from project_index.features.documents.types import Document
from project_index.features.seen.types import LastRead, SessionKey
from project_index.features.sources.types import DocumentTable
from project_index.features.write.apply import apply_operation, expand_array_keys, to_columns
from project_index.features.write.hints import attach_schema_hints
from project_index.features.write.ids import generate_id
from project_index.features.write.placement import new_document_path
from project_index.features.write.types import (
    OPERATIONS_MAX,
    DeleteRequest,
    DeleteResult,
    DeleteTarget,
    Operation,
    WriteRequest,
    WriteResult,
    WriteResultItem,
)
from project_index.integrations.scripts import ScriptError, run_script
from project_index.shared.errors import (
    DeleteNotAllowedError,
    DocumentReferencedError,
    InvalidArgumentError,
    ProjectIndexError,
    ValidationFailedError,
    VersionMismatchError,
    Violation,
)
from project_index.shared.files import replace_file
from project_index.shared.hashing import value_hash
from project_index.shared.narrowing import is_dict, is_list
from project_index.shared.yaml_io import dump_roundtrip, load_roundtrip

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping
    from pathlib import Path

    from project_index.features.seen.store import SeenStore
    from project_index.features.sources.registry import SourceRegistry
    from project_index.features.validation.markdown import UncheckedKey
    from project_index.features.validation.service import DocumentChecker
    from project_index.features.write.locks import SourceLocks

logger = logging.getLogger(__name__)


def check_version(
    document: Document, expected: str | Mapping[str, str], *, last_read: LastRead | None
) -> None:
    """`expected_version` が今の文書と同じかを確かめる。"""
    if isinstance(expected, str):
        same = document.version == expected
    else:
        same = all(
            value_hash(get_field(document.data, path)) == digest
            for path, digest in expected.items()
        )
    if same:
        return
    diff = diff_lines(last_read.content, document.body) if last_read is not None else ""
    raise VersionMismatchError(
        message=f"{document.id} は参照した後に変わっています（今のバージョン {document.version}）",
        doc_id=document.id,
        current=document.version,
        diff=diff,
        next_steps=["search_docs で再取得してから、新しいバージョンで再実行してください"],
    )


def _invalid(violations: list[Violation]) -> InvalidArgumentError:
    """引数の違反を `InvalidArgumentError` にする。"""
    return InvalidArgumentError(
        message=f"引数が正しくありません: {len(violations)} 件", violations=violations
    )


def _check_operations(operations: list[Operation]) -> None:
    """件数と `op` ごとの必須のキーを確かめる。"""
    if not 1 <= len(operations) <= OPERATIONS_MAX:
        raise _invalid(
            [
                Violation(
                    path="operations",
                    rule=f"1〜{OPERATIONS_MAX} 件にしてください（今: {len(operations)} 件）",
                    fix="操作を分けて呼んでください",
                )
            ]
        )
    required = {
        "create": ("kind", "data"),
        "update": ("id", "expected_version"),
        "replace": ("id", "expected_version", "data"),
    }
    violations = [
        Violation(path=f"operations[{index}].{name}", rule=f"{operation.op} には {name} が要ります")
        for index, operation in enumerate(operations)
        for name in required[operation.op]
        if getattr(operation, name) is None
    ]
    if violations:
        raise _invalid(violations)


def _related_column(table: DocumentTable) -> str:
    """参照を持つ列（種類の行の `metadata.related` の列名。無ければ `related`）。"""
    return table.metadata.get("related", "related")


@dataclass
class _Session:
    """1 回の書き込み・削除の作業状態（今の文書と、書き込み前の新しい内容）。"""

    store: DocumentStore
    target: Target
    docs: dict[str, Document] = field(default_factory=dict[str, Document])
    pending: dict[str, str | None] = field(default_factory=dict[str, str | None])
    tables: dict[str, DocumentTable] = field(default_factory=dict[str, DocumentTable])
    # mdmark の CLI が無い・制限時間を超えたときの理由。後の操作の点検を飛ばす
    markdown_stopped: str | None = None

    def __post_init__(self) -> None:
        self.docs = {document.id: document for document in self.store.load(self.target).documents}

    @property
    def source_id(self) -> str:
        return self.target.source.id

    def text(self, path: str) -> str:
        """ファイルの内容（まだ書いていない新しい内容があればそれ）。"""
        pending = self.pending.get(path)
        if pending is not None:
            return pending
        return (self.target.base / path).read_text(encoding="utf-8")

    def exists(self, path: str) -> bool:
        """ファイルがあるか（書く予定のものを含む）。"""
        if path in self.pending:
            return self.pending[path] is not None
        return (self.target.base / path).is_file()

    def build(self, path: str, text: str, table: DocumentTable) -> list[Document]:
        """内容から文書を組み立てる（書かずに確かめる）。"""
        found, _ = documents_from_text(
            text, self.target.base, path, table, source_id=self.source_id
        )
        return found

    def commit(self, path: str, text: str | None, table: DocumentTable) -> None:
        """新しい内容を記録し、今の文書をそれに差し替える。"""
        self.pending[path] = text
        self.docs = {
            doc_id: document
            for doc_id, document in self.docs.items()
            if not (document.path == path and document.kind == table.id)
        }
        if text is not None:
            self.docs.update({d.id: d for d in self.build(path, text, table)})

    def write_pending(self) -> list[Path]:
        """記録した内容をファイルへ書き、消す予定のファイルを消して、触ったパスを返す。"""
        touched: list[Path] = []
        for path, text in self.pending.items():
            absolute = self.target.base / path
            if text is None:
                absolute.unlink(missing_ok=True)
            else:
                replace_file(absolute, text)
            touched.append(absolute)
        self.store.invalidate(touched)
        return touched


def _prefixed(index: int, error: ProjectIndexError) -> list[Violation]:
    """失敗した操作の違反を、添字つきのパスにそろえる。"""
    if isinstance(error, InvalidArgumentError | ValidationFailedError):
        # `replace` で、書き込みの違反が持つスキーマの説明（`schema`）も保つ
        return [
            dataclasses.replace(
                violation,
                path=violation.path
                if violation.path.startswith("operations[")
                else f"operations[{index}].{violation.path}",
                index=index,
                doc=None,
            )
            for violation in error.violations
        ]
    return [
        Violation(
            path=f"operations[{index}]",
            rule=error.message,
            fix=" ".join(error.next_steps),
            index=index,
        )
    ]


def _stamp(
    content: MutableMapping[str, Any], op: str, now: datetime, old: Mapping[str, Any] | None
) -> None:
    """Git 管理外の配信元では `created`・`updated` を入れる。"""
    stamp = now.isoformat()
    if op == "create":
        set_field(content, "created", stamp)
    elif op == "replace":
        created = old.get("created") if old else None
        set_field(content, "created", created or stamp)
    set_field(content, "updated", stamp)


def _records(file_map: CommentedMap, records: str) -> list[object]:
    """ファイルの内容から `records` の配列を返す。"""
    rows = get_field(file_map, records)
    if not is_list(rows):
        msg = f"{records} が配列ではありません"
        raise RuntimeError(msg)
    return rows


def _content_for(
    table: DocumentTable, text: str, document: Document | None, path: str
) -> tuple[CommentedMap, CommentedMap]:
    """ファイルの内容から、操作を当てる対象（辞書）と、書き戻すための入れ物を返す。"""
    file_map = load_roundtrip(text, file=path)
    if table.records is not None and document is not None and document.record_index is not None:
        record = _records(file_map, table.records)[document.record_index]
        if not isinstance(record, CommentedMap):
            msg = f"{path} の {table.records} の要素が辞書ではありません"
            raise RuntimeError(msg)
        return record, file_map
    return file_map, file_map


def _finish(
    table: DocumentTable,
    content: Mapping[str, Any],
    container: CommentedMap | None,
    document: Document | None,
) -> str:
    """操作を当てた内容を、ファイルの内容の文字列にする。"""
    if (
        table.records is not None
        and document is not None
        and document.record_index is not None
        and container is not None
    ):
        _records(container, table.records)[document.record_index] = content
        return dump_roundtrip(container)
    return dump_roundtrip(
        CommentedMap(content) if not isinstance(content, CommentedMap) else content
    )


def _apply_existing(
    session: _Session,
    operation: Operation,
    document: Document,
    table: DocumentTable,
    now: datetime,
) -> tuple[str, str]:
    """`update`・`replace` を当てた、(ファイルのパス, 新しい内容) を返す。"""
    text = session.text(document.path)
    current, container = _content_for(table, text, document, document.path)
    new_content = apply_operation(current, operation)
    if operation.op == "replace":
        new_content = CommentedMap(new_content)
    if not session.target.source.is_git:
        _stamp(new_content, operation.op, now, current)
    return document.path, _finish(table, new_content, container, document)


def _apply_create(
    session: _Session,
    operation: Operation,
    table: DocumentTable,
    doc_id: str,
    now: datetime,
) -> tuple[str, str, bool]:
    """`create` を当てた、(ファイルのパス, 新しい内容, 配列への追加か) を返す。"""
    path, append = new_document_path(table, doc_id)
    data = apply_operation(None, operation)
    set_field(data, table.metadata.get("id", "id"), doc_id)
    if not session.target.source.is_git:
        _stamp(data, "create", now, None)
    if append:
        text = session.text(path) if session.exists(path) else ""
        file_map = load_roundtrip(text, file=path) if text else CommentedMap()
        if table.records is None:
            msg = "文書の行に records がありません"
            raise RuntimeError(msg)
        if get_field(file_map, table.records) is None:
            set_field(file_map, table.records, [])
        _records(file_map, table.records).append(data)
        return path, dump_roundtrip(file_map), True
    if session.exists(path):
        raise _invalid(
            [Violation(path="id", rule=f"{path} は既にあります", fix="別の ID にしてください")]
        )
    return path, dump_roundtrip(CommentedMap(data)), False


def _new_document(documents: list[Document], index: int | None, doc_id: str | None) -> Document:
    """ファイルから組み立てた文書のうち、操作の対象を選ぶ。"""
    if index is not None:
        for document in documents:
            if document.record_index == index:
                return document
    if doc_id is not None:
        for document in documents:
            if document.id == doc_id:
                return document
    return documents[0]


def _check_and_commit(
    session: _Session,
    checker: DocumentChecker,
    table: DocumentTable,
    path: str,
    text: str,
    *,
    index: int | None,
    doc_id: str | None,
    new: bool,
    previous: Mapping[str, Any] | None,
) -> tuple[Document, list[UncheckedKey]]:
    """新しい内容を文書にして検査し、通れば記録する（点検できなかった Markdown のキーも返す）。"""
    documents = session.build(path, text, table)
    if not documents:
        raise ValidationFailedError(
            message="検査に通らない操作があります: 1 件",
            violations=[Violation(path="$", rule="文書として読み込めません")],
        )
    document = _new_document(documents, index, doc_id)
    violations = checker.check(session.target, document, on="write", new=new)
    unchecked: list[UncheckedKey] = []
    # 検査に通った文書だけ、変えた Markdown の値を mdmark の点検に通す
    if not violations:
        markdown = checker.check_markdown(
            session.target, document, previous=previous, stopped=session.markdown_stopped
        )
        session.markdown_stopped = markdown.stopped
        violations = markdown.violations
        unchecked = markdown.unchecked
    if violations:
        # スキーマの違反に、違反した項目のスキーマの説明を添える
        schema = checker.store.row_schema(session.target, document.kind)
        hinted: list[Violation] = [
            *attach_schema_hints(violations, schema=schema, data=document.data)
        ]
        raise ValidationFailedError(
            message=f"検査に通らない操作があります: {len(hinted)} 件", violations=hinted
        )
    session.commit(path, text, table)
    return document, unchecked


def _unique(tables: list[DocumentTable]) -> list[DocumentTable]:
    """文書の行を ID の重なりを除いて、出た順に返す。"""
    return list({table.id: table for table in tables}.values())


def _run_generators(
    target: Target, tables: list[DocumentTable], paths: list[Path], timeout_sec: float
) -> None:
    """`after_write` の生成を、ID の重なりを除いて順に動かす。"""
    done: set[str] = set()
    for table in tables:
        for generator_id in table.after_write:
            if generator_id in done:
                continue
            done.add(generator_id)
            try:
                entry = target.source.script("generators", generator_id)
                run_script(
                    entry.run,
                    cwd=target.config_base,
                    args=[str(path) for path in paths],
                    timeout_sec=timeout_sec,
                )
            except (ScriptError, KeyError) as error:
                logger.warning(
                    "書き込み後の生成に失敗した（%s・%s・%s）",
                    target.source.id,
                    generator_id,
                    error,
                )


def _atomic_error(failures: list[tuple[int, ProjectIndexError]]) -> ProjectIndexError:
    """まとめて当てる要求で失敗した操作があるときに送る例外を作る。"""
    first = failures[0][1]
    # 検査の不合格: 全ての操作の違反を添字つきのパスでまとめる
    if isinstance(first, ValidationFailedError):
        violations = [
            violation
            for index, error in failures
            if isinstance(error, ValidationFailedError)
            for violation in _prefixed(index, error)
        ]
        return ValidationFailedError(
            message=f"検査に通らない操作があります: {len(violations)} 件",
            violations=violations,
            next_steps=["違反を修正してから再実行してください"],
        )
    # 引数の誤り: 最初に失敗した操作の違反を、添字つきのパスにして送る
    if isinstance(first, InvalidArgumentError):
        return InvalidArgumentError(
            message=first.message,
            violations=_prefixed(failures[0][0], first),
            next_steps=first.next_steps,
        )
    return first


def write_docs(
    request: WriteRequest,
    *,
    registry: SourceRegistry,
    store: DocumentStore,
    checker: DocumentChecker,
    seen: SeenStore,
    locks: SourceLocks,
    timeout_sec: float,
    now: datetime | None = None,
) -> WriteResult:
    """`write_docs` の要求を処理して書き込みの結果を返す。"""
    now = now or datetime.now(UTC)
    _check_operations(request.operations)
    target = resolve_write_target(
        registry=registry, source=request.source, worktree=request.worktree, cwd=request.cwd
    )
    source = target.source
    key = SessionKey.of(request.session_id, request.agent_id)
    with locks.hold(source.id):
        session = _Session(store, target)
        last_reads = seen.last_read(key, source.id)
        results: list[WriteResultItem] = []
        failures: list[tuple[int, ProjectIndexError]] = []
        written_ids: list[str] = []
        written_tables: list[DocumentTable] = []
        created_ids: set[str] = set()
        for index, operation in enumerate(request.operations):
            try:
                item = _apply_one(session, checker, operation, index, last_reads, created_ids, now)
            except ProjectIndexError as error:
                failures.append((index, error))
                results.append(
                    WriteResultItem(
                        index=index,
                        id=operation.id,
                        status="failed",
                        errors=_prefixed(index, error),
                    )
                )
                continue
            results.append(item[0])
            written_ids.append(item[0].id or "")
            written_tables.append(item[1])
        if failures and request.atomic:
            raise _atomic_error(failures)
        succeeded = [item for item in results if item.status != "failed"]
        if request.dry_run or not succeeded:
            return WriteResult(applied=False, results=results)
        touched = session.write_pending()
        _run_generators(target, _unique(written_tables), touched, timeout_sec)
        seen.record_activity(key, source.id, [i for i in written_ids if i], "edited")
        return WriteResult(applied=True, results=results)


def _writable(table: DocumentTable, path: str) -> DocumentTable:
    """書き込みを許す種類の行を返す（許さなければ `InvalidArgumentError`）。"""
    if not table.is_writable:
        raise _invalid(
            [
                Violation(
                    path=path,
                    rule=f"{table.id} は書き込みを許していません",
                    fix="documents[].writable を確認してください",
                )
            ]
        )
    return table


def _new_id(
    session: _Session,
    operation: Operation,
    table: DocumentTable,
    columns: Mapping[str, Any],
    created_ids: set[str],
) -> str:
    """作る文書の ID を決める（指定が無ければ `ids.format` で作る）。"""
    source = session.target.source
    doc_id = operation.id or columns.get("id")
    if doc_id is None:
        if source.config.ids_format is None:
            raise _invalid(
                [
                    Violation(
                        path="id",
                        rule="id が要ります（ids.format が無いため作れません）",
                        fix="id を指定するか、project-index.yaml に ids.format を設定してください",
                    )
                ]
            )
        doc_id = generate_id(
            source.config.ids_format,
            kind=table.id,
            data=columns,
            existing={*session.docs, *created_ids},
        )
    doc_id = str(doc_id)
    if doc_id in session.docs or doc_id in created_ids:
        raise _invalid(
            [Violation(path="id", rule=f"{doc_id} は既にあります", fix="別の ID にしてください")]
        )
    return doc_id


def _apply_one(
    session: _Session,
    checker: DocumentChecker,
    operation: Operation,
    index: int,
    last_reads: Mapping[str, LastRead],
    created_ids: set[str],
    now: datetime,
) -> tuple[WriteResultItem, DocumentTable]:
    """操作 1 件を当てて検査し、通れば記録する。"""
    if operation.op == "create":
        return _apply_create_one(session, checker, operation, index, created_ids, now)
    return _apply_existing_one(session, checker, operation, index, last_reads, now)


def _apply_create_one(
    session: _Session,
    checker: DocumentChecker,
    operation: Operation,
    index: int,
    created_ids: set[str],
    now: datetime,
) -> tuple[WriteResultItem, DocumentTable]:
    """`create` 1 件を当てて検査し、通れば記録する。"""
    if operation.kind is None:
        msg = "create に kind がありません"
        raise RuntimeError(msg)
    table = _writable(session.target.source.table(operation.kind), "kind")
    operation = expand_array_keys(operation, table, None, index=index)
    operation = to_columns(operation, table, index=index)
    doc_id = _new_id(
        session, operation, table, resolve_metadata(operation.data or {}, table), created_ids
    )
    path, text, appended = _apply_create(session, operation, table, doc_id, now)
    # 配列へ追加した文書は、配列の末尾の要素
    index_in_file = (
        len(_records(load_roundtrip(text), table.records or "")) - 1 if appended else None
    )
    document, unchecked = _check_and_commit(
        session,
        checker,
        table,
        path,
        text,
        index=index_in_file,
        doc_id=doc_id,
        new=True,
        previous=None,
    )
    created_ids.add(document.id)
    return (
        WriteResultItem(
            index=index,
            id=document.id,
            status="created",
            version=document.version,
            diff=diff_lines("", document.body),
            unchecked=unchecked,
        ),
        table,
    )


def _apply_existing_one(
    session: _Session,
    checker: DocumentChecker,
    operation: Operation,
    index: int,
    last_reads: Mapping[str, LastRead],
    now: datetime,
) -> tuple[WriteResultItem, DocumentTable]:
    """`update`・`replace` 1 件を当てて検査し、通れば記録する。"""
    if operation.id is None:
        msg = "操作に id がありません"
        raise RuntimeError(msg)
    existing = session.docs.get(operation.id)
    if existing is None:
        raise not_found_error(session.source_id, [operation.id], list(session.docs))
    table = _writable(session.target.source.table(existing.kind), "id")
    current = existing.data if operation.op == "update" else None
    operation = expand_array_keys(operation, table, current, index=index)
    operation = to_columns(operation, table, index=index)
    if operation.expected_version is None:
        msg = "操作に expected_version がありません"
        raise RuntimeError(msg)
    check_version(existing, operation.expected_version, last_read=last_reads.get(existing.id))
    path, text = _apply_existing(session, operation, existing, table, now)
    new_document, unchecked = _check_and_commit(
        session,
        checker,
        table,
        path,
        text,
        index=existing.record_index,
        doc_id=None,
        new=False,
        previous=existing.data,
    )
    return (
        WriteResultItem(
            index=index,
            id=new_document.id,
            status="updated" if operation.op == "update" else "replaced",
            version=new_document.version,
            diff=diff_lines(existing.body, new_document.body),
            unchecked=unchecked,
        ),
        table,
    )


def _points_to(row: object, ids: set[str]) -> bool:
    """関連の行が、`source` を持たずに `ids` のどれかを `to` で指すか。"""
    if not is_dict(row):
        return False
    to = row.get("to")
    return isinstance(to, str) and to in ids and "source" not in row


def _referrers(session: _Session, doc_id: str, leaving: set[str]) -> list[Document]:
    """残る文書のうち、`related` の `to` が消す文書の ID で `source` の無い行を持つ文書を返す。"""
    found: list[Document] = []
    for document in session.docs.values():
        if document.id in leaving:
            continue
        rows: object = document.metadata.get("related")
        if is_list(rows) and any(_points_to(row, {doc_id}) for row in rows):
            found.append(document)
    return found


def _unlink(session: _Session, referrer: Document, removed: set[str]) -> tuple[str, str]:
    """参照元の `related` の列から、消す文書を指す行を除いた、(パス, 新しい内容) を返す。"""
    table = session.target.source.table(referrer.kind)
    column = _related_column(table)
    text = session.text(referrer.path)
    current, container = _content_for(table, text, referrer, referrer.path)
    rows = get_field(current, column)
    if not is_list(rows):
        msg = "related の列が配列ではありません"
        raise RuntimeError(msg)
    rows[:] = [row for row in rows if not _points_to(row, removed)]
    return referrer.path, _finish(table, current, container, referrer)


def _remove_documents(session: _Session, documents: list[Document]) -> None:
    """ファイル 1 つの文書はファイルを消し、`records` の文書は配列から要素を除く。"""
    source = session.target.source
    records = sorted(
        (document for document in documents if document.record_index is not None),
        key=lambda document: (document.path, -(document.record_index or 0)),
    )
    for document in documents:
        if document.record_index is None:
            session.commit(document.path, None, source.table(document.kind))
    for document in records:
        table = source.table(document.kind)
        if table.records is None:
            msg = "文書の行に records がありません"
            raise RuntimeError(msg)
        file_map = load_roundtrip(session.text(document.path), file=document.path)
        del _records(file_map, table.records)[document.record_index or 0]
        session.commit(document.path, dump_roundtrip(file_map), table)


def _delete_target(
    session: _Session, item: DeleteTarget, leaving: set[str], on_referenced: str
) -> tuple[Document, list[Document]]:
    """消す文書と、その文書を参照している文書を返す（消せなければ例外を送る）。"""
    source = session.target.source
    document = session.docs.get(item.id)
    if document is None:
        raise not_found_error(session.source_id, [item.id], list(session.docs))
    table = source.table(document.kind)
    if not source.is_git and not table.is_writable:
        raise DeleteNotAllowedError(
            message=f"{table.id} は削除を許していません（documents[].writable）",
            kind=table.id,
        )
    check_version(document, item.expected_version, last_read=None)
    referrers = _referrers(session, item.id, leaving)
    if referrers and on_referenced == "fail":
        names = ", ".join(referrer.id for referrer in referrers)
        raise DocumentReferencedError(
            message=f"{item.id} は {names} から参照されています",
            doc_id=item.id,
            referrers=[referrer.id for referrer in referrers],
            next_steps=["on_referenced に unlink を指定すると、参照も除外して削除できます"],
        )
    return document, referrers


def _apply_unlinks(
    session: _Session, checker: DocumentChecker, unlink_plan: Mapping[str, set[str]]
) -> None:
    """参照元の `related` から消す文書を指す行を除き、検査に通れば記録する。"""
    target = session.target
    for referrer_id, removed in unlink_plan.items():
        referrer = session.docs[referrer_id]
        table = target.source.table(referrer.kind)
        path, text = _unlink(session, referrer, removed)
        changed = _new_document(
            session.build(path, text, table), referrer.record_index, referrer.id
        )
        violations = checker.check(target, changed, on="write")
        if violations:
            raise ValidationFailedError(
                message=f"検査に通らない操作があります: {len(violations)} 件",
                violations=violations,
            )
        session.commit(path, text, table)


def delete_docs(
    request: DeleteRequest,
    *,
    registry: SourceRegistry,
    store: DocumentStore,
    checker: DocumentChecker,
    locks: SourceLocks,
    timeout_sec: float,
) -> DeleteResult:
    """`delete_docs` の要求を処理して削除の結果を返す。"""
    if not 1 <= len(request.targets) <= OPERATIONS_MAX:
        raise _invalid(
            [
                Violation(
                    path="targets",
                    rule=f"1〜{OPERATIONS_MAX} 件にしてください（今: {len(request.targets)} 件）",
                    fix="対象を分けて呼んでください",
                )
            ]
        )
    target = resolve_write_target(
        registry=registry, source=request.source, worktree=request.worktree, cwd=request.cwd
    )
    source = target.source
    with locks.hold(source.id):
        session = _Session(store, target)
        leaving = {item.id for item in request.targets}
        results: list[WriteResultItem] = []
        failures: list[tuple[int, ProjectIndexError]] = []
        accepted: list[Document] = []
        unlink_plan: dict[str, set[str]] = {}
        for index, item in enumerate(request.targets):
            try:
                document, referrers = _delete_target(session, item, leaving, request.on_referenced)
            except ProjectIndexError as error:
                failures.append((index, error))
                results.append(
                    WriteResultItem(
                        index=index, id=item.id, status="failed", errors=_prefixed(index, error)
                    )
                )
                continue
            for referrer in referrers:
                unlink_plan.setdefault(referrer.id, set()).add(item.id)
            accepted.append(document)
            results.append(WriteResultItem(index=index, id=item.id, status="deleted"))
        if failures and request.atomic:
            raise failures[0][1]
        _apply_unlinks(session, checker, unlink_plan)
        # 参照を外した文書と、外した後のバージョン
        unlinked = [(referrer_id, session.docs[referrer_id].version) for referrer_id in unlink_plan]
        if request.dry_run or not accepted:
            return DeleteResult(applied=False, results=results, unlinked=unlinked)
        _remove_documents(session, accepted)
        touched = session.write_pending()
        _run_generators(
            target,
            _unique([source.table(d.kind) for d in accepted]),
            touched,
            timeout_sec,
        )
        return DeleteResult(applied=True, results=results, unlinked=unlinked)

"""`write_docs`・`delete_docs` の処理。"""

from __future__ import annotations

import dataclasses
import logging
import posixpath
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from ruamel.yaml.comments import CommentedMap

from project_index.features.access.service import resolve_write_target
from project_index.features.access.types import Target
from project_index.features.changes.compare import diff_lines
from project_index.features.documents.fields import (
    field_arrays,
    get_field,
    resolve_metadata,
    set_field,
)
from project_index.features.documents.loader import (
    documents_from_text,
    lacks_body_file,
    resolve_body_path,
)
from project_index.features.documents.store import DocumentStore, not_found_error
from project_index.features.documents.types import Document
from project_index.features.search.fields import known_fields
from project_index.features.search.filters import check_filter, match_filter
from project_index.features.search.types import SearchRequest
from project_index.features.seen.types import LastRead, SessionKey
from project_index.features.sources.types import DocumentTable
from project_index.features.write.apply import (
    BODY_KEY,
    apply_body,
    apply_operation,
    expand_array_keys,
    to_columns,
)
from project_index.features.write.hints import attach_schema_hints
from project_index.features.write.ids import generate_id
from project_index.features.write.placement import new_document_path
from project_index.features.write.references import (
    renamed_path,
    rewrite_body_references,
    rewrite_references,
)
from project_index.features.write.replace import replace_in_body, replace_in_values
from project_index.features.write.types import (
    OPERATIONS_MAX,
    DeleteRequest,
    DeleteResult,
    DeleteTarget,
    Operation,
    ReferenceChange,
    WriteRequest,
    WriteResult,
    WriteResultItem,
)
from project_index.integrations.scripts import ScriptError, run_script
from project_index.shared.deadline import Deadline
from project_index.shared.errors import (
    DeleteNotAllowedError,
    DocumentReferencedError,
    InvalidArgumentError,
    ProjectIndexError,
    ValidationFailedError,
    VersionMismatchError,
    Violation,
    WriteDeadlineExceededError,
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
    from project_index.shared.deadline import CallLimits

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
        "rename": ("id", "expected_version"),
        "replace_text": ("filter", "old", "new"),
    }
    violations = [
        Violation(path=f"operations[{index}].{name}", rule=f"{operation.op} には {name} が要ります")
        for index, operation in enumerate(operations)
        for name in required[operation.op]
        if getattr(operation, name) is None
    ]
    violations += [
        Violation(
            path=f"operations[{index}].new_id",
            rule="rename には new_id か new_path が要ります",
            fix="改名後の ID（new_id）かパス（new_path）を指定してください",
        )
        for index, operation in enumerate(operations)
        if operation.op == "rename" and operation.new_id is None and operation.new_path is None
    ]
    violations += [
        Violation(
            path=f"operations[{index}].old",
            rule="old は空にできません",
            fix="置換する前の文字列を指定してください",
        )
        for index, operation in enumerate(operations)
        if operation.op == "replace_text" and operation.old == ""
    ]
    if violations:
        raise _invalid(violations)


def _related_column(table: DocumentTable) -> str:
    """参照を持つ列（種類の行の `metadata.related` の列名。無ければ `related`）。"""
    return table.metadata.get("related", "related")


@dataclass(frozen=True)
class _Snapshot:
    """操作の前の作業状態。"""

    docs: dict[str, Document]
    pending: dict[str, str | None]
    bodies: dict[str, str | None]
    markdown_stopped: str | None


@dataclass
class _Session:
    """1 回の書き込み・削除の作業状態（今の文書と、書き込み前の新しい内容）。"""

    store: DocumentStore
    target: Target
    docs: dict[str, Document] = field(default_factory=dict[str, Document])
    pending: dict[str, str | None] = field(default_factory=dict[str, str | None])
    # 本文のファイルの新しい内容（`None` は消す）。管理用の YAML より先に書く
    bodies: dict[str, str | None] = field(default_factory=dict[str, str | None])
    tables: dict[str, DocumentTable] = field(default_factory=dict[str, DocumentTable])
    # mdmark の CLI が無い・制限時間を超えたときの理由。後の操作の点検を飛ばす
    markdown_stopped: str | None = None
    # 書き込みの期限（文書の MCP から呼ばれたときだけ）。検査と点検の制限時間を切る
    deadline: Deadline | None = None

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

    def read_body(self, path: str, bodies: Mapping[str, str | None] | None = None) -> str | None:
        """本文のファイルの内容（書く予定の内容があればそれ。無いファイルは `None`）。"""
        for overlay in (bodies or {}, self.bodies):
            if path in overlay:
                return overlay[path]
        absolute = self.target.base / path
        try:
            return absolute.read_text(encoding="utf-8") if absolute.is_file() else None
        except OSError, UnicodeDecodeError:
            return None

    def body_exists(self, path: str) -> bool:
        """本文のファイルがあるか（書く予定のものを含む）。"""
        return self.read_body(path) is not None

    def build(
        self,
        path: str,
        text: str,
        table: DocumentTable,
        bodies: Mapping[str, str | None] | None = None,
    ) -> list[Document]:
        """内容から文書を組み立てる（書かずに確かめる）。本文は書く予定の内容で読む。"""
        found, _ = documents_from_text(
            text,
            self.target.base,
            path,
            table,
            source_id=self.source_id,
            read_body=lambda body_path: self.read_body(body_path, bodies),
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

    def snapshot(self) -> _Snapshot:
        """操作の前の状態を返す（失敗した操作の変更を戻すため）。"""
        return _Snapshot(
            docs=dict(self.docs),
            pending=dict(self.pending),
            bodies=dict(self.bodies),
            markdown_stopped=self.markdown_stopped,
        )

    def restore(self, snapshot: _Snapshot) -> None:
        """操作の前の状態へ戻す。"""
        self.docs = snapshot.docs
        self.pending = snapshot.pending
        self.bodies = snapshot.bodies
        self.markdown_stopped = snapshot.markdown_stopped

    def write_pending(self) -> list[Path]:
        """記録した内容をファイルへ書き、消す予定のファイルを消して、触ったパスを返す。"""
        touched: list[Path] = []
        # 本文のファイルを先に書き、管理用の YAML が指すファイルを先にそろえる
        for path, text in [*self.bodies.items(), *self.pending.items()]:
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


def _writes_dates(session: _Session, table: DocumentTable) -> bool:
    """書き換える文書に `created`・`updated` を付けるか（Git 管理外で、種類の行が許すとき）。"""
    return not session.target.source.is_git and table.write_dates


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
    original: str,
) -> str:
    """操作を当てた内容を、元のファイルの配列の字下げのまま、ファイルの内容の文字列にする。"""
    if (
        table.records is not None
        and document is not None
        and document.record_index is not None
        and container is not None
    ):
        _records(container, table.records)[document.record_index] = content
        return dump_roundtrip(container, original=original)
    return dump_roundtrip(
        CommentedMap(content) if not isinstance(content, CommentedMap) else content,
        original=original,
    )


def _apply_existing(
    session: _Session,
    operation: Operation,
    document: Document,
    table: DocumentTable,
    now: datetime,
    schema: Mapping[str, Any],
) -> tuple[str, str]:
    """`update`・`replace` を当てた、(ファイルのパス, 新しい内容) を返す。"""
    text = session.text(document.path)
    current, container = _content_for(table, text, document, document.path)
    new_content = apply_operation(current, operation, schema=schema)
    if operation.op == "replace":
        new_content = CommentedMap(new_content)
    if _writes_dates(session, table):
        _stamp(new_content, operation.op, now, current)
    return document.path, _finish(table, new_content, container, document, text)


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
    if _writes_dates(session, table):
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
        # 既にある管理用の YAML へ追加するときは、元のファイルの配列の字下げに合わせる
        return path, dump_roundtrip(file_map, original=text or None), True
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
    bodies: Mapping[str, str] | None = None,
) -> tuple[Document, list[UncheckedKey]]:
    """新しい内容を文書にして検査し、通れば記録する（点検できなかった Markdown のキーも返す）。"""
    documents = session.build(path, text, table, bodies)
    if not documents:
        raise ValidationFailedError(
            message="検査に通らない操作があります: 1 件",
            violations=[Violation(path="$", rule="文書として読み込めません")],
        )
    document = _new_document(documents, index, doc_id)
    violations = checker.check(
        session.target, document, on="write", new=new, deadline=session.deadline
    )
    unchecked: list[UncheckedKey] = []
    # 検査に通った文書だけ、変えた Markdown の値を mdmark の点検に通す
    if not violations:
        markdown = checker.check_markdown(
            session.target,
            document,
            previous=previous,
            stopped=session.markdown_stopped,
            deadline=session.deadline,
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
    session.bodies.update(bodies or {})
    session.commit(path, text, table)
    return document, unchecked


def _body_paths(operation: Operation) -> list[str]:
    """操作が `@body` を指す箇所の、違反の項目のパスを返す。"""
    paths = [
        f"{item}.{BODY_KEY}"
        for item, given in (("data", operation.data or {}), ("set", operation.set))
        if BODY_KEY in given
    ]
    paths += [
        f"text_edits[{n}].field"
        for n, edit in enumerate(operation.text_edits)
        if edit.field == BODY_KEY
    ]
    return paths


def _check_body(operation: Operation, table: DocumentTable, existing: Document | None) -> None:
    """`@body` を受け付ける操作かと、`body_file` の列の値を変えないかを確かめる。"""
    violations = _misplaced_body(operation)
    if table.body_file is None:
        violations.extend(
            Violation(
                path=path,
                rule=f"{table.id} は本文のファイル（body_file）を持たないため {BODY_KEY} を受けません",
                fix=f"{BODY_KEY} を除いてください",
            )
            for path in _body_paths(operation)
        )
    elif operation.op == "create":
        violations.extend(_one_sided_body(operation, table, "data", operation.data or {}))
    elif existing is not None and existing.body_path is None:
        # 本文のファイルを持たない要素: 列の値と本文を同時に渡したときだけ本文のファイルを作る
        item, given = _given(operation)
        violations.extend(_one_sided_body(operation, table, item, given))
        violations.extend(
            Violation(
                path=path,
                rule=f"{existing.id} は本文のファイルを持たないため {BODY_KEY} を一部だけ書き換えられません",
                fix=f"本文を作るときは set に {table.body_file} と {BODY_KEY} を指定してください",
            )
            for path in _body_paths(operation)
            if path.startswith("text_edits[")
        )
    elif existing is not None:
        violations.extend(_moved_body(operation, table.body_file, existing))
    if violations:
        raise _invalid(violations)


def _given(operation: Operation) -> tuple[str, Mapping[str, Any]]:
    """`update` は `set`、`create`・`replace` は `data` の (項目名, 値)。"""
    if operation.op == "update":
        return "set", operation.set
    return "data", operation.data or {}


_ABSENT = object()


def _column_value(operation: Operation, column: str) -> tuple[bool, object]:
    """操作が `body_file` の列を持つかと、その値を返す。

    `update` の `set` は項目のパス（`meta.path`）をキーに持つため、キーの一致で引く。
    `create`・`replace` の `data` は入れ子の辞書のため、項目のパスをたどって引く。
    """
    if operation.op == "update":
        return column in operation.set, operation.set.get(column)
    value = get_field(operation.data or {}, column, default=_ABSENT)
    return value is not _ABSENT, None if value is _ABSENT else value


def _has_body_path(operation: Operation, column: str) -> bool:
    """操作が `body_file` の列に、本文のファイルのパスになりうる値（`None`・空の文字列でない）を持つか。"""
    if operation.op == "update":
        value = operation.set.get(column)
        return value is not None and value != ""
    # `data` は読み込みと同じ判定（『本文のファイルを持たない要素の判定』）
    return not lacks_body_file(operation.data or {}, column)


def _one_sided_body(
    operation: Operation, table: DocumentTable, item: str, given: Mapping[str, Any]
) -> list[Violation]:
    """`body_file` の列の値と `@body` の片方だけを渡したときの違反（両方とも無ければ本文なし）。"""
    column = table.body_file or ""
    has_column = _has_body_path(operation, column)
    has_body = BODY_KEY in given
    # 本文だけ: 本文のファイルのパスが決まらない
    if has_body and not has_column:
        return [
            Violation(
                path=f"{item}.{column}",
                rule=f"{BODY_KEY} を書くには本文のファイルのパス（{column}）が要ります",
                fix=f"{item} に {column} を加えるか、{BODY_KEY} を除いてください",
            )
        ]
    # 列の値だけ: 作る本文のファイルの中身が無い
    if has_column and not has_body:
        return _missing_body(operation, table, item)
    return []


def _misplaced_body(operation: Operation) -> list[Violation]:
    """`unset`・`add_to`・`remove_from` に渡した `@body` の違反。"""
    violations: list[Violation] = []
    if BODY_KEY in operation.unset:
        violations.append(
            Violation(path="unset", rule=f"{BODY_KEY} は消せません", fix="unset から除いてください")
        )
    violations.extend(
        Violation(
            path=f"{item}.{BODY_KEY}",
            rule=f"{BODY_KEY} は配列の項目ではありません",
            fix=f"本文は set.{BODY_KEY} か text_edits で書いてください",
        )
        for item, given in (("add_to", operation.add_to), ("remove_from", operation.remove_from))
        if BODY_KEY in given
    )
    return violations


def _missing_body(operation: Operation, table: DocumentTable, item: str) -> list[Violation]:
    """本文のファイルのパスを渡したのに本文が無いときの違反。"""
    _, given = _given(operation)
    if BODY_KEY in given:
        return []
    return [
        Violation(
            path=f"{item}.{BODY_KEY}",
            rule=f"{table.id} の本文のファイルの作成には本文（{BODY_KEY}）が要ります",
            fix=f"{item} に {BODY_KEY} を加えるか、{table.body_file} を除いてください",
        )
    ]


def _moved_body(operation: Operation, column: str, existing: Document) -> list[Violation]:
    """`update`・`replace` で `body_file` の列の値を変える（除くことを含む）ときの違反。"""
    item, _ = _given(operation)
    present, value = _column_value(operation, column)
    current = get_field(existing.data, column)
    # `unset` で列を除く: 本文のファイルを外す操作は無い
    if operation.op == "update" and column in operation.unset:
        return [
            Violation(
                path=f"unset.{column}",
                rule=f"{column}（本文のファイルのパス）は除けません",
                fix=f"unset から {column} を除いてください",
            )
        ]
    # `replace` の data に列が無い: 置き換えで列が無くなる
    if operation.op == "replace" and not present:
        return [
            Violation(
                path=f"data.{column}",
                rule=f"{column}（本文のファイルのパス）は除けません",
                fix=f"data に今の値（{current}）の {column} を加えてください",
            )
        ]
    if not present or value == current:
        return []
    return [
        Violation(
            path=f"{item}.{column}",
            rule=f"{column}（本文のファイルのパス）は変えられません",
            fix=f"{column} を除くか、今の値（{current}）にしてください",
        )
    ]


def _create_body(
    session: _Session,
    operation: Operation,
    table: DocumentTable,
    path: str,
    index: int,
) -> dict[str, str]:
    """`create` の本文のファイルのパスを解き、(パス → 本文) を返す（作れなければ違反）。"""
    column = table.body_file
    if column is None:
        return {}
    _, given = _given(operation)
    # 列の値も本文も無い: 本文のファイルを持たない要素のまま
    if not _has_body_path(operation, column) and BODY_KEY not in given:
        return {}
    _, value = _column_value(operation, column)
    body_path = resolve_body_path(path, value)
    if body_path is None or session.body_exists(body_path):
        rule = (
            f"本文のファイルのパス（{value}）が配信元の外を指します"
            if body_path is None
            else f"本文のファイル {body_path} は既にあります"
        )
        raise ValidationFailedError(
            message="検査に通らない操作があります: 1 件",
            violations=[
                Violation(
                    path=column,
                    rule=rule,
                    fix=f"{column} に、管理用の YAML のフォルダからの相対で、配信元の中の新しいファイルのパスを指定してください",
                )
            ],
        )
    body = apply_body(None, operation, index=index)
    if body is None:
        msg = "本文のファイルを作る操作に本文がありません"
        raise RuntimeError(msg)
    return {body_path: body}


def _diff(before: Document | None, after: Document, body: Mapping[str, str]) -> str:
    """差分の行。本文のファイルを持つ文書は、要素の差分の後に本文のファイルの差分を並べる。"""
    if after.body_path is None:
        return diff_lines("" if before is None else before.body, after.body)
    element = diff_lines(
        "" if before is None else _element_text(before.data), _element_text(after.data)
    )
    if after.body_path not in body:
        return element
    lines = [element] if element else []
    lines += [
        f"@@ {after.body_path}",
        diff_lines("" if before is None or before.body_path is None else before.body, after.body),
    ]
    return "\n".join(lines)


def _element_text(data: Mapping[str, Any]) -> str:
    """`records` の要素を YAML に書き出した文字列。"""
    return dump_roundtrip(data if isinstance(data, CommentedMap) else CommentedMap(data))


def _unique(tables: list[DocumentTable]) -> list[DocumentTable]:
    """文書の行を ID の重なりを除いて、出た順に返す。"""
    return list({table.id: table for table in tables}.values())


def _run_generators(
    target: Target,
    tables: list[DocumentTable],
    paths: list[Path],
    timeout_sec: float,
    respond_by: Deadline | None = None,
) -> None:
    """`after_write` の生成を、ID の重なりを除いて順に動かす（応答の上限までの時間で切る）。"""
    done: set[str] = set()
    for table in tables:
        for generator_id in table.after_write:
            if generator_id in done:
                continue
            done.add(generator_id)
            limit = timeout_sec if respond_by is None else respond_by.cap(timeout_sec)
            # 応答の上限まで時間が無い: 生成を動かさない（書き込みの結果は変えない）
            if limit <= 0:
                logger.warning(
                    "応答の上限までの時間が無いため書き込み後の生成を実行しなかった（%s・%s）",
                    target.source.id,
                    generator_id,
                )
                continue
            try:
                entry = target.source.script("generators", generator_id)
                run_script(
                    entry.run,
                    cwd=target.config_base,
                    args=[str(path) for path in paths],
                    timeout_sec=limit,
                )
            except (ScriptError, KeyError) as error:
                logger.warning(
                    "書き込み後の生成に失敗した（%s・%s・%s）",
                    target.source.id,
                    generator_id,
                    error,
                )


def _check_before_write(limits: CallLimits | None) -> None:
    """ファイルを置き換える前に書き込みの期限を確かめる（過ぎていれば何も書かずに超過を送る）。"""
    if limits is not None:
        limits.write_deadline.check()


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
    limits: CallLimits | None = None,
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
        session = _Session(
            store, target, deadline=None if limits is None else limits.write_deadline
        )
        applied = _apply_operations(
            session, checker, request.operations, seen.last_read(key, source.id), now
        )
        results = applied.results
        if applied.failures and request.atomic:
            raise _atomic_error(applied.failures)
        succeeded = [item for item in results if item.status != "failed"]
        if request.dry_run or not succeeded:
            return WriteResult(applied=False, results=results)
        _check_before_write(limits)
        touched = session.write_pending()
        _run_generators(
            target,
            _unique(applied.tables),
            touched,
            timeout_sec,
            None if limits is None else limits.respond_by,
        )
        seen.record_activity(key, source.id, [i for i in applied.ids if i], "edited")
        return WriteResult(applied=True, results=results)


@dataclass
class _Applied:
    """操作を順に当てた結果（行・失敗・書いた文書の ID と種類の行）。"""

    results: list[WriteResultItem] = field(default_factory=list[WriteResultItem])
    failures: list[tuple[int, ProjectIndexError]] = field(
        default_factory=list[tuple[int, ProjectIndexError]]
    )
    ids: list[str] = field(default_factory=list[str])
    tables: list[DocumentTable] = field(default_factory=list[DocumentTable])


def _apply_operations(
    session: _Session,
    checker: DocumentChecker,
    operations: list[Operation],
    last_reads: Mapping[str, LastRead],
    now: datetime,
) -> _Applied:
    """操作を順に当てる。失敗した操作は `failed` の行にして次へ進む。"""
    applied = _Applied()
    created_ids: set[str] = set()
    for index, operation in enumerate(operations):
        # 複数の文書を書き換える操作は、途中で失敗したら操作の前の状態へ戻す
        snapshot = session.snapshot()
        try:
            done = _apply_one(session, checker, operation, index, last_reads, created_ids, now)
        except WriteDeadlineExceededError:
            # 期限の超過は操作の失敗にせず、`atomic` によらず全体を止める
            raise
        except ProjectIndexError as error:
            session.restore(snapshot)
            applied.failures.append((index, error))
            applied.results.append(
                WriteResultItem(
                    index=index, id=operation.id, status="failed", errors=_prefixed(index, error)
                )
            )
            continue
        for item, table in done:
            applied.results.append(item)
            applied.ids.append(item.id or "")
            applied.tables.append(table)
    return applied


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
) -> list[tuple[WriteResultItem, DocumentTable]]:
    """操作 1 件を当てて検査し、通れば記録する（結果の行は、書き換えた文書ごと）。"""
    if operation.op == "create":
        return [_apply_create_one(session, checker, operation, index, created_ids, now)]
    if operation.op == "rename":
        return _apply_rename_one(session, checker, operation, index, last_reads, now)
    if operation.op == "replace_text":
        return _apply_replace_text_one(session, checker, operation, index, now)
    return [_apply_existing_one(session, checker, operation, index, last_reads, now)]


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
    _check_body(operation, table, None)
    doc_id = _new_id(
        session, operation, table, resolve_metadata(operation.data or {}, table), created_ids
    )
    path, text, appended = _apply_create(session, operation, table, doc_id, now)
    body = _create_body(session, operation, table, path, index)
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
        bodies=body,
    )
    created_ids.add(document.id)
    return (
        WriteResultItem(
            index=index,
            id=document.id,
            status="created",
            version=document.version,
            diff=_diff(None, document, body),
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
    _check_body(operation, table, existing)
    # 本文のファイルを持つ文書は本文を当て、持たない要素は列の値と本文があれば本文のファイルを作る
    if existing.body_path is not None:
        new_body = apply_body(existing.body, operation, index=index)
        body = {} if new_body is None else {existing.body_path: new_body}
    else:
        body = _create_body(session, operation, table, existing.path, index)
    schema = checker.store.row_schema(session.target, existing.kind)
    path, text = _apply_existing(session, operation, existing, table, now, schema)
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
        bodies=body,
    )
    return (
        WriteResultItem(
            index=index,
            id=new_document.id,
            status="updated" if operation.op == "update" else "replaced",
            version=new_document.version,
            diff=_diff(existing, new_document, body),
            unchecked=unchecked,
        ),
        table,
    )


def _skip_columns(table: DocumentTable) -> list[str]:
    """参照の書き換えと置換で触らない列（ID の列と `body_file` の列）。"""
    columns = [table.metadata.get("id", "id")]
    if table.body_file is not None:
        columns.append(table.body_file)
    return columns


def _markdown_body(document: Document, seen: set[str]) -> str | None:
    """書き換える本文のファイルのパス（拡張子が `.md` で、同じ操作でまだ扱っていないもの）。"""
    path = document.body_path
    if path is None or not path.endswith(".md") or path in seen:
        return None
    seen.add(path)
    return path


def _rename_invalid(rule: str, fix: str, path: str = "new_path") -> InvalidArgumentError:
    """改名の引数の誤り。"""
    return _invalid([Violation(path=path, rule=rule, fix=fix)])


@dataclass(frozen=True)
class _RenamePlan:
    """改名の前後の ID とパス。"""

    old_id: str
    new_id: str
    # 1 ファイル 1 文書の YAML のパス（`records` の文書は管理用の YAML のパスのまま）
    file_path: str
    # パスが変わるときの（改名前のパス, 改名後のパス）
    moved: tuple[str, str] | None


def _plan_body_move(
    session: _Session, operation: Operation, table: DocumentTable, existing: Document
) -> tuple[str, str] | None:
    """`body_file` の文書の本文のファイルの移し先を確かめ、（改名前, 改名後）を返す。"""
    if operation.new_path is None or existing.body_path is None:
        return None
    new_path = posixpath.normpath(operation.new_path)
    relative = posixpath.relpath(new_path, posixpath.dirname(existing.path) or ".")
    if resolve_body_path(existing.path, relative) != new_path:
        rule = f"new_path（{operation.new_path}）が配信元の外を指します"
        raise _rename_invalid(
            rule,
            "配信元の直下からのパスを指定してください",
        )
    if new_path == existing.body_path:
        return None
    if session.body_exists(new_path):
        rule = f"new_path（{new_path}）は既にあります"
        raise _rename_invalid(rule, "別のパスを指定してください")
    return existing.body_path, new_path


def _plan_file_move(
    session: _Session, operation: Operation, table: DocumentTable, existing: Document
) -> tuple[str, str] | None:
    """1 ファイル 1 文書の YAML の移し先を確かめ、（改名前, 改名後）を返す。"""
    if operation.new_path is not None:
        new_path = posixpath.normpath(operation.new_path)
    elif operation.new_id is not None:
        new_path = renamed_path(existing.path, old_id=existing.id, new_id=operation.new_id)
        if new_path is None:
            return None
    else:
        return None
    if new_path == existing.path:
        return None
    if not table.matches(new_path):
        rule = f"new_path（{new_path}）が {table.id} の paths に該当しないか exclude に該当します"
        raise _rename_invalid(
            rule,
            f"{table.id} の documents[].paths に該当するパスを指定してください",
        )
    if session.exists(new_path):
        rule = f"new_path（{new_path}）は既にあります"
        raise _rename_invalid(rule, "別のパスを指定してください")
    return existing.path, new_path


def _id_exists(new_id: str) -> ValidationFailedError:
    """改名後の ID が既にある文書と重なる違反。"""
    return ValidationFailedError(
        message="検査に通らない操作があります: 1 件",
        violations=[
            Violation(path="new_id", rule=f"{new_id} は既にあります", fix="別の ID にしてください")
        ],
    )


def _renamed_id(
    session: _Session,
    operation: Operation,
    existing: Document,
    *,
    has_id: bool,
    moved: tuple[str, str] | None,
) -> str:
    """改名後の ID（ID の列の値を持つ文書は `new_id`、ID がパスの文書は改名後のパス）。"""
    if has_id:
        new_id = operation.new_id or existing.id
    else:
        new_id = existing.id if moved is None else moved[1]
    if new_id != existing.id and new_id in session.docs:
        raise _id_exists(new_id)
    return new_id


def _plan_rename(
    session: _Session, operation: Operation, table: DocumentTable, existing: Document
) -> _RenamePlan:
    """改名の前後の ID とパスを決める（引数の誤りは `InvalidArgumentError`）。"""
    id_column = table.metadata.get("id", "id")
    has_id = get_field(existing.data, id_column) is not None
    if operation.new_id is not None and not has_id:
        rule = f"{existing.id} は ID がパスの文書のため new_id を受けません"
        raise _rename_invalid(
            rule,
            "new_path で改名してください",
            path="new_id",
        )
    # ID の重なりは、移し先のファイルの重なりより先に ID の違反として返す
    if operation.new_id not in (None, existing.id) and operation.new_id in session.docs:
        raise _id_exists(operation.new_id)
    if table.records is not None and table.body_file is None and operation.new_path is not None:
        rule = f"{table.id} は本文のファイル（body_file）を持たないため new_path を受けません"
        raise _rename_invalid(
            rule,
            "new_path を除いてください",
        )
    if (
        table.body_file is not None
        and existing.body_path is None
        and operation.new_path is not None
    ):
        rule = f"{existing.id} は本文のファイルを持たないため new_path を受けません"
        raise _rename_invalid(rule, "new_path を除いてください")
    if table.records is not None:
        moved = _plan_body_move(session, operation, table, existing)
        file_path = existing.path
    else:
        moved = _plan_file_move(session, operation, table, existing)
        file_path = existing.path if moved is None else moved[1]
    new_id = _renamed_id(session, operation, existing, has_id=has_id, moved=moved)
    return _RenamePlan(old_id=existing.id, new_id=new_id, file_path=file_path, moved=moved)


def _renamed_content(
    session: _Session,
    table: DocumentTable,
    existing: Document,
    plan: _RenamePlan,
    now: datetime,
) -> str:
    """改名した文書の新しい内容（ID・本文のファイルの列・自分を指す参照を書き換えたもの）。"""
    text = session.text(existing.path)
    current, container = _content_for(table, text, existing, existing.path)
    id_column = table.metadata.get("id", "id")
    if get_field(current, id_column) is not None and plan.new_id != plan.old_id:
        set_field(current, id_column, plan.new_id)
    if table.body_file is not None and plan.moved is not None:
        relative = posixpath.relpath(plan.moved[1], posixpath.dirname(existing.path) or ".")
        set_field(current, table.body_file, relative)
    # 改名した文書の中の、自分を指す参照（パスは解き直さない）
    rewrite_references(
        current,
        related_column=_related_column(table),
        old_id=plan.old_id,
        new_id=plan.new_id,
        moved=None,
        base_dir=posixpath.dirname(existing.path),
        skip=_skip_columns(table),
    )
    if _writes_dates(session, table):
        _stamp(current, "update", now, None)
    return _finish(table, current, container, existing, text)


def _rewritten_body(
    session: _Session, document: Document, plan: _RenamePlan, seen: set[str]
) -> tuple[dict[str, str], list[ReferenceChange]] | None:
    """参照元の本文のファイルの旧 ID・旧パスを指すリンクを書き換え、新しい本文と箇所を返す。"""
    path = _markdown_body(document, seen)
    current = None if path is None else session.read_body(path)
    if path is None or current is None:
        return None
    body, changes = rewrite_body_references(
        current,
        old_id=plan.old_id,
        new_id=plan.new_id,
        moved=plan.moved,
        base_dir=posixpath.dirname(path),
    )
    return ({path: body}, changes) if changes else None


def _rewrite_referrers(
    session: _Session,
    checker: DocumentChecker,
    plan: _RenamePlan,
    index: int,
    now: datetime,
) -> list[tuple[WriteResultItem, DocumentTable]]:
    """同じ配信元のほかの文書の、改名前の ID・パスを指す箇所を書き換える。"""
    done: list[tuple[WriteResultItem, DocumentTable]] = []
    seen: set[str] = set()
    for doc_id in list(session.docs):
        document = session.docs.get(doc_id)
        if document is None or doc_id == plan.new_id:
            continue
        table = session.target.source.table(document.kind)
        text = session.text(document.path)
        current, container = _content_for(table, text, document, document.path)
        changes = rewrite_references(
            current,
            related_column=_related_column(table),
            old_id=plan.old_id,
            new_id=plan.new_id,
            moved=plan.moved,
            base_dir=posixpath.dirname(document.path),
            skip=_skip_columns(table),
        )
        body = _rewritten_body(session, document, plan, seen)
        if body is not None:
            changes = [*changes, *body[1]]
        bodies = {} if body is None else body[0]
        if not changes:
            continue
        table = _writable(table, "id")
        if _writes_dates(session, table):
            _stamp(current, "update", now, None)
        new_text = _finish(table, current, container, document, text)
        new_document, unchecked = _check_and_commit(
            session,
            checker,
            table,
            document.path,
            new_text,
            index=document.record_index,
            doc_id=None,
            new=False,
            previous=document.data,
            bodies=bodies,
        )
        done.append(
            (
                WriteResultItem(
                    index=index,
                    id=new_document.id,
                    status="updated",
                    version=new_document.version,
                    diff=_diff(document, new_document, bodies),
                    unchecked=unchecked,
                    references=changes,
                ),
                table,
            )
        )
    return done


def _apply_rename_one(
    session: _Session,
    checker: DocumentChecker,
    operation: Operation,
    index: int,
    last_reads: Mapping[str, LastRead],
    now: datetime,
) -> list[tuple[WriteResultItem, DocumentTable]]:
    """`rename` 1 件を当てて、改名した文書と参照元を検査し、通れば記録する。"""
    if operation.id is None or operation.expected_version is None:
        msg = "rename に id か expected_version がありません"
        raise RuntimeError(msg)
    existing = session.docs.get(operation.id)
    if existing is None:
        raise not_found_error(session.source_id, [operation.id], list(session.docs))
    table = _writable(session.target.source.table(existing.kind), "id")
    check_version(existing, operation.expected_version, last_read=last_reads.get(existing.id))
    plan = _plan_rename(session, operation, table, existing)
    text = _renamed_content(session, table, existing, plan, now)
    body: dict[str, str | None] = {}
    if table.body_file is not None and plan.moved is not None:
        body = {plan.moved[1]: existing.body, plan.moved[0]: None}
    if table.records is None and plan.file_path != existing.path:
        session.commit(existing.path, None, table)
    renamed, unchecked = _check_and_commit(
        session,
        checker,
        table,
        plan.file_path,
        text,
        index=existing.record_index,
        doc_id=plan.new_id,
        new=False,
        previous=existing.data,
        bodies=body,  # type: ignore[arg-type]
    )
    item = WriteResultItem(
        index=index,
        id=renamed.id,
        status="renamed",
        version=renamed.version,
        diff=_diff(existing, renamed, {}),
        unchecked=unchecked,
        path=renamed.body_path or renamed.path,
        renamed_from=existing.id,
    )
    return [(item, table), *_rewrite_referrers(session, checker, plan, index, now)]


def _columns(paths: list[str] | None, table: DocumentTable) -> list[str] | None:
    """項目のパスの先頭の共通のキーを、種類の行の列名へ読み替える。"""
    if paths is None:
        return None
    result: list[str] = []
    for path in paths:
        head, dot, rest = path.partition(".")
        column = table.metadata.get(head, head)
        result.append(f"{column}{dot}{rest}")
    return result


def _matched(session: _Session, checker: DocumentChecker, operation: Operation) -> list[str]:
    """`filter` に該当する、書き込みを許す種類の文書の ID を返す。"""
    source = session.target.source
    schemas = [
        checker.store.row_schema(session.target, table.id)
        for table in source.config.documents
        if table.enabled
    ]
    fields = known_fields(schemas)
    violations = check_filter(SearchRequest(filter=operation.filter), fields)
    if violations:
        raise _invalid(violations)
    today = datetime.now(UTC).astimezone().date()
    return [
        document.id
        for document in session.docs.values()
        if source.table(document.kind).is_writable
        and match_filter(operation.filter, document, fields=fields, today=today)
    ]


def _replaced_body(
    session: _Session, document: Document, old: str, new: str, seen: set[str]
) -> tuple[dict[str, str], int]:
    """本文のファイルの `old` を `new` にした本文と件数を返す（置換が無ければ空と 0）。"""
    path = _markdown_body(document, seen)
    current = None if path is None else session.read_body(path)
    if path is None or current is None:
        return {}, 0
    body, found = replace_in_body(current, old=old, new=new)
    return ({path: body} if found else {}), found


def _commit_replaced(
    session: _Session,
    checker: DocumentChecker,
    table: DocumentTable,
    document: Document,
    text: str,
    bodies: Mapping[str, str],
) -> tuple[Document, list[UncheckedKey]]:
    """置換した文書を検査して記録する。違反には項目のパスの前に文書の ID を付ける。"""
    try:
        return _check_and_commit(
            session,
            checker,
            table,
            document.path,
            text,
            index=document.record_index,
            doc_id=None,
            new=False,
            previous=document.data,
            bodies=bodies,
        )
    except ValidationFailedError as error:
        raise ValidationFailedError(
            message=error.message,
            violations=[
                dataclasses.replace(violation, path=f"{document.id}#{violation.path}")
                for violation in error.violations
            ],
        ) from error


def _apply_replace_text_one(
    session: _Session,
    checker: DocumentChecker,
    operation: Operation,
    index: int,
    now: datetime,
) -> list[tuple[WriteResultItem, DocumentTable]]:
    """`replace_text` 1 件を、`filter` に該当する文書ごとに当てて検査し、全て通れば記録する。"""
    if operation.old is None or operation.new is None:
        msg = "replace_text に old か new がありません"
        raise RuntimeError(msg)
    done: list[tuple[WriteResultItem, DocumentTable]] = []
    fields = operation.fields
    value_fields = None if fields is None else [path for path in fields if path != BODY_KEY]
    with_body = fields is None or BODY_KEY in fields
    seen: set[str] = set()
    for doc_id in _matched(session, checker, operation):
        document = session.docs[doc_id]
        table = session.target.source.table(document.kind)
        text = session.text(document.path)
        current, container = _content_for(table, text, document, document.path)
        count = replace_in_values(
            current,
            old=operation.old,
            new=operation.new,
            fields=_columns(value_fields, table),
            skip=_skip_columns(table),
        )
        bodies, found = (
            _replaced_body(session, document, operation.old, operation.new, seen)
            if with_body
            else ({}, 0)
        )
        count += found
        if count == 0:
            continue
        if _writes_dates(session, table):
            _stamp(current, "update", now, None)
        new_text = _finish(table, current, container, document, text)
        new_document, unchecked = _commit_replaced(
            session, checker, table, document, new_text, bodies
        )
        done.append(
            (
                WriteResultItem(
                    index=index,
                    id=new_document.id,
                    status="updated",
                    version=new_document.version,
                    diff=_diff(document, new_document, bodies),
                    unchecked=unchecked,
                    count=count,
                ),
                table,
            )
        )
    return done


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
    arrays = field_arrays(current, column)
    if not arrays:
        msg = "related の列が配列ではありません"
        raise RuntimeError(msg)
    # `**.` の列名では、最上位と入れ子の全ての配列から除く
    for rows in arrays:
        rows[:] = [row for row in rows if not _points_to(row, removed)]
    return referrer.path, _finish(table, current, container, referrer, text)


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
        text = session.text(document.path)
        file_map = load_roundtrip(text, file=document.path)
        del _records(file_map, table.records)[document.record_index or 0]
        session.commit(document.path, dump_roundtrip(file_map, original=text), table)
    _remove_bodies(session, [document for document in records if document.body_path is not None])


def _remove_bodies(session: _Session, documents: list[Document]) -> None:
    """消した要素の本文のファイルを、同じ管理用の YAML の残る要素が指していなければ消す。"""
    source = session.target.source
    for document in documents:
        table = source.table(document.kind)
        if table.records is None or table.body_file is None or document.body_path is None:
            continue
        file_map = load_roundtrip(session.text(document.path), file=document.path)
        remaining = {
            resolve_body_path(
                document.path, get_field(cast("Mapping[str, Any]", row), table.body_file)
            )
            for row in _records(file_map, table.records)
            if is_dict(row)
        }
        if document.body_path not in remaining and session.body_exists(document.body_path):
            session.bodies[document.body_path] = None


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
        violations = checker.check(target, changed, on="write", deadline=session.deadline)
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
    limits: CallLimits | None = None,
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
        session = _Session(
            store, target, deadline=None if limits is None else limits.write_deadline
        )
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
        _check_before_write(limits)
        _remove_documents(session, accepted)
        touched = session.write_pending()
        _run_generators(
            target,
            _unique([source.table(d.kind) for d in accepted]),
            touched,
            timeout_sec,
            None if limits is None else limits.respond_by,
        )
        return DeleteResult(applied=True, results=results, unlinked=unlinked)

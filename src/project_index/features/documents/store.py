"""文書のキャッシュと ID の引き当て。"""

from __future__ import annotations

import difflib
import hashlib
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from project_index.features.access.types import Target
from project_index.features.documents.aliases import collect_aliases
from project_index.features.documents.fields import missing_ref_fields, unresolved_related
from project_index.features.documents.indexable import walk_files
from project_index.features.documents.loader import collect_files, load_file, unindexed_files
from project_index.features.documents.schema import (
    records_item_schema,
    resolve_schema_refs,
    startup_schema,
)
from project_index.features.documents.types import Document, LoadProblem, LoadResult, SyncReport
from project_index.features.history.query import file_dates, resolve_ref
from project_index.features.history.types import FileDates
from project_index.integrations.git import GitError, run_git
from project_index.shared.errors import DocumentNotFoundError
from project_index.shared.narrowing import is_dict
from project_index.shared.yaml_io import YamlLoadError, load_yaml

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from project_index.features.history.snapshot import SnapshotStore
    from project_index.features.sources.types import DocumentTable, ServedSource

logger = logging.getLogger(__name__)

CANDIDATE_COUNT = 5
CANDIDATE_CUTOFF = 0.6
TREE_KEEP = 20

__all__ = [
    "CANDIDATE_COUNT",
    "CANDIDATE_CUTOFF",
    "TREE_KEEP",
    "DocumentStore",
    "check_sync",
    "collect_files",
    "load_file",
]


def not_found_error(source_id: str, missing: list[str], known: list[str]) -> DocumentNotFoundError:
    """無い ID ごとに近い ID を添えた `DocumentNotFoundError` を作る。"""
    return DocumentNotFoundError(
        message=f"{source_id}: 文書 {', '.join(missing)} はありません",
        missing=missing,
        candidates={
            document_id: difflib.get_close_matches(
                document_id, known, n=CANDIDATE_COUNT, cutoff=CANDIDATE_CUTOFF
            )
            for document_id in missing
        },
        next_steps=["search_docs で ID を探してください"],
    )


type _BodyStamps = tuple[tuple[str, int, int], ...]
type _CachedFile = tuple[int, int, list[Document], list[LoadProblem], _BodyStamps]
type _BodyBlobs = tuple[tuple[str, str], ...]
type _DateStamps = tuple[tuple[str, FileDates | None], ...]
type _RevisionKey = tuple[Path, str, str, str, str]
type _CachedRevisionFile = tuple[str, _BodyBlobs, _DateStamps, list[Document], list[LoadProblem]]


def _table_hash(table: DocumentTable) -> str:
    """文書の行の定義の全ての項目から作るハッシュを返す。"""
    return hashlib.sha256(repr(table).encode("utf-8")).hexdigest()


def _date_stamps(
    path: str, documents: Sequence[Document], dates: dict[str, FileDates]
) -> _DateStamps:
    """ファイルと、文書が指す本文のファイルの (パス, 日時) を、パスの順に返す。"""
    paths = {path} | {d.body_path for d in documents if d.body_path is not None}
    return tuple((item, dates.get(item)) for item in sorted(paths))


def _body_stamps(root: Path, documents: Sequence[Document]) -> _BodyStamps:
    """文書が指す本文のファイルの (パス, 更新日時, 大きさ) を、パスの順に返す。"""
    stamps: list[tuple[str, int, int]] = []
    for path in sorted({d.body_path for d in documents if d.body_path is not None}):
        try:
            stat = (root / path).stat()
        except OSError:
            continue
        stamps.append((path, stat.st_mtime_ns, stat.st_size))
    return tuple(stamps)


class DocumentStore:
    """読む場所ごとに文書を集め、ファイルごとに結果をキャッシュする。"""

    def __init__(self, snapshots: SnapshotStore) -> None:
        self.snapshots = snapshots
        self._files: dict[tuple[Path, str], _CachedFile] = {}
        self._schemas: dict[Path, tuple[int, int, dict[str, Any]]] = {}
        self._revision_schemas: dict[tuple[Path, str, str], dict[str, Any]] = {}
        self._revision_files: dict[_RevisionKey, _CachedRevisionFile] = {}
        self._trees: dict[tuple[Path, str], dict[str, str]] = {}
        self._dates: dict[tuple[Path, str, str], dict[str, FileDates]] = {}
        self._lock = threading.Lock()

    def read_root(self, target: Target) -> Path:
        """読むフォルダを決める（`ref` があればリビジョンを書き出す）。"""
        if target.ref is None:
            return target.base
        return self._revision_root(target, self._commit_of(target))

    def _commit_of(self, target: Target) -> str:
        """`ref` を持つ読む場所の commit を返す（`commit` が無いときだけ解く）。"""
        if target.commit is not None:
            return target.commit
        if target.ref is None:
            msg = "読む場所に ref がありません"
            raise RuntimeError(msg)
        source = target.source
        repo_root = source.repo_root or source.root
        return resolve_ref(repo_root, target.ref, date_base=source.config.default_ref).commit

    def _revision_root(self, target: Target, commit: str) -> Path:
        """commit を書き出したフォルダの下の、配信元の直下を返す。"""
        source = target.source
        repo_root = source.repo_root or source.root
        checkout = self.snapshots.checkout(repo_root, commit)
        return checkout / source.root.relative_to(repo_root)

    def location(self, target: Target, document: Document) -> str | None:
        """文書のファイルの絶対パスを返す（リビジョンを読んだ文書は `None`）。"""
        if target.ref is not None:
            return None
        return str(self.read_root(target) / (document.body_path or document.path))

    def _file_dates(self, target: Target, revision: str | None) -> dict[str, FileDates]:
        """Git の配信元のファイルの日時を、配信元の直下からのパスで返す。"""
        source = target.source
        if not source.is_git:
            return {}
        repo_root = source.repo_root or source.root
        work_root = target.worktree or repo_root
        if revision is not None:
            commit = revision
        else:
            try:
                output = run_git(["rev-parse", "HEAD"], cwd=work_root)
            except GitError:
                # commit がまだ 1 つも無いリポジトリ
                return {}
            commit = (output if isinstance(output, str) else output.decode("utf-8")).strip()
        prefix = source.root.relative_to(repo_root).as_posix()
        key = (work_root, commit, prefix)
        with self._lock:
            cached = self._dates.get(key)
        if cached is None:
            raw = file_dates(work_root, commit=commit)
            cached = {
                path if prefix == "." else path.removeprefix(f"{prefix}/"): dates
                for path, dates in raw.items()
                if prefix == "." or path.startswith(f"{prefix}/")
            }
            with self._lock:
                self._dates[key] = cached
        return cached

    def _tables(self, target: Target, kinds: Sequence[str] | None) -> list[DocumentTable]:
        """読む文書の行を決める。"""
        source = target.source
        if kinds is not None:
            return [source.table(kind) for kind in kinds]
        return [row for row in source.config.documents if row.enabled]

    def _load_table(
        self,
        root: Path,
        table: DocumentTable,
        source_id: str,
        dates: dict[str, FileDates],
        files: Sequence[str],
    ) -> tuple[list[Document], list[LoadProblem], set[tuple[Path, str]]]:
        """1 つの文書の行のファイルを集め、変わったファイルだけ読み直す。"""
        documents: list[Document] = []
        problems: list[LoadProblem] = []
        seen: set[tuple[Path, str]] = set()
        for path in collect_files(root, table, files=files):
            absolute = root / path
            key = (absolute, table.id)
            seen.add(key)
            try:
                stat = absolute.stat()
            except OSError:
                continue
            with self._lock:
                cached = self._files.get(key)
            if (
                cached is not None
                and cached[:2] == (stat.st_mtime_ns, stat.st_size)
                and not any(issue.reason == "missing_body_file" for issue in cached[3])
                and cached[4] == _body_stamps(root, cached[2])
            ):
                found, issues = cached[2], cached[3]
            else:
                found, issues = load_file(root, path, table, source_id=source_id, dates=dates)
                stamps = _body_stamps(root, found)
                with self._lock:
                    self._files[key] = (stat.st_mtime_ns, stat.st_size, found, issues, stamps)
            documents.extend(found)
            problems.extend(issues)
        return documents, problems, seen

    def _blobs(self, repo_root: Path, commit: str) -> dict[str, str]:
        """commit のファイルの blob の SHA を、`repo_root` からの相対パスで返す。"""
        key = (repo_root, commit)
        with self._lock:
            cached = self._trees.get(key)
        if cached is not None:
            return cached
        output = run_git(
            ["-c", "core.quotepath=off", "ls-tree", "-r", "-z", "--full-tree", commit],
            cwd=repo_root,
        )
        text = output if isinstance(output, str) else output.decode("utf-8")
        blobs: dict[str, str] = {}
        for entry in text.split("\0"):
            if not entry:
                continue
            meta, path = entry.split("\t", 1)
            blobs[path] = meta.split(" ")[2]
        with self._lock:
            self._trees[key] = blobs
            while len(self._trees) > TREE_KEEP:
                del self._trees[next(iter(self._trees))]
        return blobs

    def _load_revision_table(
        self,
        target: Target,
        root: Path,
        table: DocumentTable,
        dates: dict[str, FileDates],
        files: Sequence[str],
        commit: str,
    ) -> tuple[list[Document], list[LoadProblem]]:
        """リビジョンの 1 つの文書の行のファイルを集め、blob・日時・行の定義が変わったファイルだけ読む。"""
        source = target.source
        repo_root = source.repo_root or source.root
        prefix = source.root.relative_to(repo_root).as_posix()
        blobs = self._blobs(repo_root, commit)
        table_hash = _table_hash(table)

        def from_repo(path: str) -> str:
            return path if prefix == "." else f"{prefix}/{path}"

        def body_blobs(found: Sequence[Document]) -> _BodyBlobs:
            paths = sorted({d.body_path for d in found if d.body_path is not None})
            return tuple((path, blobs.get(from_repo(path), "")) for path in paths)

        documents: list[Document] = []
        problems: list[LoadProblem] = []
        seen: set[str] = set()
        for path in collect_files(root, table, files=files):
            relative = from_repo(path)
            blob = blobs.get(relative)
            if blob is None:
                continue
            seen.add(relative)
            key = (repo_root, source.id, relative, table.id, table_hash)
            with self._lock:
                cached = self._revision_files.get(key)
            if (
                cached is not None
                and cached[0] == blob
                and not any(issue.reason == "missing_body_file" for issue in cached[4])
                and cached[1] == body_blobs(cached[3])
                and cached[2] == _date_stamps(path, cached[3], dates)
            ):
                found, issues = cached[3], cached[4]
            else:
                found, issues = load_file(root, path, table, source_id=source.id, dates=dates)
                with self._lock:
                    self._revision_files[key] = (
                        blob,
                        body_blobs(found),
                        _date_stamps(path, found, dates),
                        found,
                        issues,
                    )
            documents.extend(found)
            problems.extend(issues)
        # 今の commit に無いファイルと、行の定義が変わった結果を捨てる
        with self._lock:
            for key in [
                key
                for key in self._revision_files
                if key[:2] == (repo_root, source.id)
                and key[3] == table.id
                and (key[2] not in seen or key[4] != table_hash)
            ]:
                del self._revision_files[key]
        return documents, problems

    def load(
        self,
        target: Target,
        *,
        kinds: Sequence[str] | None = None,
        files: Sequence[str] | None = None,
    ) -> LoadResult:
        """読む場所の文書を、文書の行ごとに集めて返す。

        `files` は呼び出し元が読むフォルダを `walk_files` でたどったパス。
        無ければここで 1 回だけたどり、行ごとにたどり直さない。
        """
        revision = None if target.ref is None else self._commit_of(target)
        root = target.base if revision is None else self._revision_root(target, revision)
        tables = self._tables(target, kinds)
        dates = self._file_dates(target, revision)
        walked = list(walk_files(root)) if files is None else files
        documents: list[Document] = []
        problems: list[LoadProblem] = []
        kind_ids = {table.id for table in tables}
        seen_keys: set[tuple[Path, str]] = set()
        for table in tables:
            if revision is None:
                found, issues, seen = self._load_table(root, table, target.source.id, dates, walked)
                seen_keys |= seen
            else:
                found, issues = self._load_revision_table(
                    target, root, table, dates, walked, revision
                )
            documents.extend(found)
            problems.extend(issues)
        # 削除されたファイルのキャッシュを捨てる
        with self._lock:
            for key in [
                key
                for key in self._files
                if key[1] in kind_ids and key not in seen_keys and key[0].is_relative_to(root)
            ]:
                del self._files[key]
        first: dict[str, Document] = {}
        unique: list[Document] = []
        for document in documents:
            earlier = first.get(document.id)
            if earlier is None:
                first[document.id] = document
                unique.append(document)
            else:
                problems.append(
                    LoadProblem(
                        path=document.path,
                        reason="duplicate_id",
                        detail=f"ID {document.id} は先の文書（{earlier.path}）と重なります",
                    )
                )
        problems.sort(key=lambda problem: problem.path)
        for problem in problems:
            logger.debug("%s: %s: %s", target.source.id, problem.path, problem.reason)
        return LoadResult(documents=unique, problems=problems)

    def get(
        self, target: Target, ids: Sequence[str], *, kinds: Sequence[str] | None = None
    ) -> list[Document]:
        """ID の並びの順に文書を返す。"""
        by_id = {document.id: document for document in self.load(target, kinds=kinds).documents}
        missing = [document_id for document_id in ids if document_id not in by_id]
        if missing:
            raise not_found_error(target.source.id, missing, list(by_id))
        return [by_id[document_id] for document_id in ids]

    def schema(self, target: Target, kind: str) -> dict[str, Any]:
        """読む場所に合わせた種類のスキーマを返す。"""
        source = target.source
        table = source.table(kind)
        # 起動時のスキーマを使う: クローン本体を読むときと、ほかの配信元のリビジョンを指す行
        if (target.ref is None and target.worktree is None) or not isinstance(
            table.schema_path, str
        ):
            return startup_schema(source, table)
        startup = source.schemas.get(kind, {})
        base = source.root / table.schema_path
        if target.ref is not None:
            return self._revision_schema(target, table.schema_path, startup, base)
        path = self.read_root(target) / table.schema_path
        try:
            stat = path.stat()
        except OSError:
            return startup_schema(source, table)
        with self._lock:
            cached = self._schemas.get(path)
        if cached is not None and cached[:2] == (stat.st_mtime_ns, stat.st_size):
            return cached[2]
        try:
            raw = load_yaml(path.read_text(encoding="utf-8"), file=str(path))
        except OSError, UnicodeDecodeError, YamlLoadError:
            return startup_schema(source, table)
        if not is_dict(raw):
            return startup_schema(source, table)
        # YAML から読んだ辞書のキーは文字列として扱う
        resolved = resolve_schema_refs(cast("dict[str, Any]", raw), path)
        with self._lock:
            self._schemas[path] = (stat.st_mtime_ns, stat.st_size, resolved)
        return resolved

    def _revision_schema(
        self, target: Target, schema_path: str, startup: dict[str, Any], base: Path
    ) -> dict[str, Any]:
        """リビジョンの種類のスキーマを、commit とスキーマのファイルの相対パスで控えて返す。"""
        source = target.source
        repo_root = source.repo_root or source.root
        commit = self._commit_of(target)
        relative = (source.root.relative_to(repo_root) / schema_path).as_posix()
        key = (repo_root, commit, relative)
        with self._lock:
            cached = self._revision_schemas.get(key)
        if cached is not None:
            return cached
        path = self._revision_root(target, commit) / schema_path
        try:
            raw = load_yaml(path.read_text(encoding="utf-8"), file=str(path))
        except OSError, UnicodeDecodeError, YamlLoadError:
            return resolve_schema_refs(startup, base)
        if not is_dict(raw):
            return resolve_schema_refs(startup, base)
        resolved = resolve_schema_refs(cast("dict[str, Any]", raw), path)
        with self._lock:
            self._revision_schemas[key] = resolved
        return resolved

    def row_schema(self, target: Target, kind: str) -> dict[str, Any]:
        """文書 1 件の内容に当てるスキーマを返す（`records` を持つ行は 1 行のスキーマ）。"""
        schema = self.schema(target, kind)
        records = target.source.table(kind).records
        # ファイル 1 つが 1 文書の行: 種類のスキーマをそのまま当てる
        if records is None:
            return schema
        # records の行: 要素 1 つのスキーマ。取り出せなければ何も当てない
        return records_item_schema(schema, records) or {}

    def invalidate(self, paths: Iterable[Path]) -> None:
        """書き込んだファイルのキャッシュを捨てる。"""
        targets = set(paths)
        with self._lock:
            for key in [key for key in self._files if key[0] in targets]:
                del self._files[key]
            for path in [path for path in self._schemas if path in targets]:
                del self._schemas[path]

    def clear(self) -> None:
        """全てのキャッシュを捨てる。"""
        with self._lock:
            self._files.clear()
            self._schemas.clear()
            self._revision_schemas.clear()
            self._dates.clear()


def check_sync(store: DocumentStore, source: ServedSource) -> SyncReport:
    """配信元の文書を読み、`metadata` の列の欠け・管理用の YAML のずれ・当たらない関連・エイリアスのキーの違反を求める。"""
    # 配信元のフォルダは 1 回だけたどり、文書の収集と索引に無いファイルの検出で使い回す
    files = list(walk_files(source.root))
    result = store.load(Target(source, source.root, None, None, "read"), files=files)
    missing_refs = [
        f"{document.kind}: {document.id}: {key}（{field}）"
        for document in result.documents
        for key, field in missing_ref_fields(document.data, source.table(document.kind))
    ]
    unindexed: list[str] = []
    for table in source.config.documents:
        if not table.enabled or table.records is None or table.body_file is None:
            continue
        for index_path in collect_files(source.root, table, files=files):
            body_paths = {
                document.body_path
                for document in result.documents
                if document.kind == table.id and document.path == index_path and document.body_path
            }
            unindexed.extend(
                f"{table.id}: {path}"
                for path in unindexed_files(source.root, index_path, body_paths, table, files=files)
            )
    missing_body_files = [
        f"{problem.path}: {problem.detail}"
        for problem in result.problems
        if problem.reason == "missing_body_file"
    ]
    # 文書の ID の集合は 1 回だけ作り、全ての文書の関連の照合で使い回す
    ids = {document.id for document in result.documents}
    unresolved = [
        f"{document.kind}: {document.id}: {to}"
        for document in result.documents
        for to in unresolved_related(document.metadata, ids)
    ]
    return SyncReport(
        source_id=source.id,
        missing_refs=missing_refs,
        unindexed_files=unindexed,
        missing_body_files=missing_body_files,
        unresolved_related=unresolved,
        alias_violations=collect_aliases(source, result.documents).violations,
    )

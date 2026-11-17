"""文書のキャッシュと ID の引き当て。"""

from __future__ import annotations

import difflib
import functools
import hashlib
import logging
import os
import posixpath
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from project_index.features.access.types import Target
from project_index.features.documents.aliases import collect_aliases
from project_index.features.documents.fields import missing_ref_fields, unresolved_related
from project_index.features.documents.indexable import is_walked, walk_files, walk_tree
from project_index.features.documents.loader import (
    collect_files,
    documents_from_text,
    load_file,
    unindexed_files,
)
from project_index.features.documents.schema import (
    records_item_schema,
    resolve_schema_refs,
    startup_schema,
)
from project_index.features.documents.types import Document, LoadProblem, LoadResult, SyncReport
from project_index.features.history.blob import BlobReader
from project_index.features.history.query import file_dates, resolve_ref
from project_index.features.history.types import FileDates
from project_index.integrations.git import GitError, ignored_paths, run_git
from project_index.shared.background import BackgroundGate
from project_index.shared.errors import DocumentNotFoundError
from project_index.shared.narrowing import is_dict
from project_index.shared.yaml_io import YamlLoadError, load_yaml

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Sequence

    from project_index.features.history.snapshot import SnapshotStore
    from project_index.features.sources.types import DocumentTable, ServedSource

logger = logging.getLogger(__name__)

CANDIDATE_COUNT = 5
CANDIDATE_CUTOFF = 0.6
TREE_KEEP = 20
# 保持するワークツリーのたどった結果の数（超えたら古く使ったものから捨てる）
WORKTREE_KEEP = 20

__all__ = [
    "CANDIDATE_COUNT",
    "CANDIDATE_CUTOFF",
    "TREE_KEEP",
    "WORKTREE_KEEP",
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
# (ファイルの絶対パス, 文書の行の ID, 文書の行の定義のハッシュ)
type _FileKey = tuple[Path, str, str]
type _BodyBlobs = tuple[tuple[str, str], ...]
type _DateStamps = tuple[tuple[str, FileDates | None], ...]
type _RevisionKey = tuple[Path, str, str, str, str]
type _CachedRevisionFile = tuple[str, _BodyBlobs, _DateStamps, list[Document], list[LoadProblem]]


@dataclass(slots=True)
class _WorktreeWalk:
    """ワークツリーをたどった結果（ファイルの一覧・フォルダの更新日時・行ごとの収集の結果）。"""

    files: list[str]
    folders: dict[str, int]
    # 行の定義のハッシュ → 『ファイルの収集』の結果
    collected: dict[str, list[str]]


def _folders_fresh(root: Path, folders: dict[str, int]) -> bool:
    """記録したフォルダの更新日時が全て同じか（無くなったフォルダがあれば `False`）。"""
    for relative, mtime in folders.items():
        try:
            if os.stat(root / relative).st_mtime_ns != mtime:
                return False
        except OSError:
            return False
    return True


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

    def __init__(self, snapshots: SnapshotStore, *, gate: BackgroundGate | None = None) -> None:
        self.snapshots = snapshots
        # 裏の検査が読むとき、要求の応答中はファイル 1 件ごとに休ませる関所
        self.gate = gate if gate is not None else BackgroundGate()
        self._files: dict[_FileKey, _CachedFile] = {}
        self._schemas: dict[Path, tuple[int, int, dict[str, Any]]] = {}
        self._revision_schemas: dict[tuple[Path, str, str], dict[str, Any]] = {}
        self._revision_files: dict[_RevisionKey, _CachedRevisionFile] = {}
        self._trees: dict[tuple[Path, str], dict[str, str]] = {}
        # (`repo_root`, 配信元の ID, 解いた commit, 行の定義のハッシュ) → ファイルの収集の結果
        self._collected: dict[tuple[Path, str, str, str], list[str]] = {}
        # `repo_root` → 書き出さずに commit の blob を読む `git cat-file --batch`
        self._blob_readers: dict[Path, BlobReader] = {}
        self._dates: dict[tuple[Path, str, str], dict[str, FileDates]] = {}
        self._worktrees: dict[Path, _WorktreeWalk] = {}
        self._worktree_locks: dict[Path, threading.Lock] = {}
        # (配信元の ID, 文書の行の ID, 文書の行の定義のハッシュ) → `$ref` を解いた起動時のスキーマ
        self._startup_schemas: dict[tuple[str, str, str], dict[str, Any]] = {}
        # `clear` のたびに増やし、`clear` の前に解き始めたスキーマを書き戻さない
        self._generation = 0
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
        collected: Sequence[str] | None = None,
    ) -> tuple[list[Document], list[LoadProblem], set[_FileKey]]:
        """1 つの文書の行のファイルを集め、変わったファイルだけ再読み込みする。"""
        documents: list[Document] = []
        problems: list[LoadProblem] = []
        seen: set[_FileKey] = set()
        # 行の定義が変わったら別のキーにして、前の定義で読んだ結果を使わない（行ごとに 1 回だけ求める）
        table_hash = _table_hash(table)
        # 集め済みのパスがあればそれを使い、無ければ行の範囲で集める
        paths = collect_files(root, table, files=files) if collected is None else collected
        # ファイル 1 件ごとの照合と読み込みを、裏の処理の 1 件にする（要求のスレッドでは何もしない）
        for path in self.gate.each(paths):
            absolute = root / path
            key = (absolute, table.id, table_hash)
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
        links: dict[str, str] = {}
        for entry in text.split("\0"):
            if not entry:
                continue
            meta, path = entry.split("\t", 1)
            mode, kind, sha = meta.split(" ")
            # サブモジュール（commit）は持たない
            if kind != "blob":
                continue
            # シンボリックリンクは、リンク先を解いてから持つ
            if mode == _SYMLINK_MODE:
                links[path] = sha
                continue
            blobs[path] = sha
        blobs.update(self._link_blobs(repo_root, links, blobs))
        with self._lock:
            self._trees[key] = blobs
            while len(self._trees) > TREE_KEEP:
                dropped = next(iter(self._trees))
                del self._trees[dropped]
                # 捨てた commit の収集の結果も捨てる
                for collected in [k for k in self._collected if (k[0], k[2]) == dropped]:
                    del self._collected[collected]
        return blobs

    def _link_blobs(
        self, repo_root: Path, links: dict[str, str], blobs: dict[str, str]
    ) -> dict[str, str]:
        """リンク先が同じ commit の通常のファイルのシンボリックリンクを、リンク先の blob で返す。"""
        if not links:
            return {}
        reader = self._blob_reader(repo_root)
        resolved: dict[str, str] = {}
        for path, sha in links.items():
            target = reader.read_text(sha)
            if target is None:
                continue
            linked = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
            # リポジトリの外を指すリンクと、リンク先の無いリンクは持たない（書き出しでも読めない）
            if linked in blobs:
                resolved[path] = blobs[linked]
        return resolved

    def _blob_reader(self, repo_root: Path) -> BlobReader:
        """リポジトリの blob の読み取りを返す（無ければ作る）。"""
        with self._lock:
            reader = self._blob_readers.get(repo_root)
            if reader is None:
                reader = self._blob_readers[repo_root] = BlobReader(repo_root)
            return reader

    def _commit_files(self, target: Target, commit: str) -> list[str]:
        """commit のファイルのうち、配信元の直下の下にあり、たどるパスに当たるものを配信元の直下からのパスで返す。"""
        source = target.source
        repo_root = source.repo_root or source.root
        prefix = source.root.relative_to(repo_root).as_posix()
        blobs = self._blobs(repo_root, commit)
        # 配信元の直下がリポジトリの直下: 全てのパスがそのまま配信元の直下からのパス
        if prefix == ".":
            return [path for path in blobs if is_walked(path)]
        head = f"{prefix}/"
        return [
            path.removeprefix(head)
            for path in blobs
            if path.startswith(head) and is_walked(path.removeprefix(head))
        ]

    def _load_revision_table(
        self,
        target: Target,
        root: Path,
        table: DocumentTable,
        dates: dict[str, FileDates],
        files: Sequence[str],
        commit: str,
        reader: BlobReader | None = None,
    ) -> tuple[list[Document], list[LoadProblem]]:
        """リビジョンの 1 つの文書の行のファイルを集め、blob・日時・行の定義が変わったファイルだけ読む。

        `reader` があれば、書き出しを読まずに commit の blob の内容から読む。
        """
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

        def load(path: str, blob: str) -> tuple[list[Document], list[LoadProblem]]:
            """書き出しを読む / 書き出さずに commit の blob の内容から読む。"""
            if reader is None:
                return load_file(root, path, table, source_id=source.id, dates=dates)
            return _documents_from_blob(
                reader,
                blob,
                _body_reader(reader, blobs, from_repo),
                root,
                path,
                table,
                source_id=source.id,
                dates=dates,
            )

        documents: list[Document] = []
        problems: list[LoadProblem] = []
        seen: set[str] = set()
        collected = self._collected_files(
            (repo_root, source.id, commit, table_hash), root, table, files
        )
        # ファイル 1 件ごとの照合と読み込みを、裏の処理の 1 件にする（要求のスレッドでは何もしない）
        for path in self.gate.each(collected):
            relative = from_repo(path)
            blob = blobs.get(relative)
            if blob is None:
                continue
            seen.add(relative)
            found, issues = self._read_revision(
                (repo_root, source.id, relative, table.id, table_hash),
                blob,
                body_blobs,
                functools.partial(_date_stamps, path, dates=dates),
                functools.partial(load, path, blob),
            )
            documents.extend(found)
            problems.extend(issues)
        # 今の commit に無いファイルと、行の定義が変わった結果を捨てる
        self._discard_revisions((repo_root, source.id), table.id, seen, table_hash)
        return documents, problems

    def _read_revision(
        self,
        key: _RevisionKey,
        blob: str,
        body_blobs: Callable[[Sequence[Document]], _BodyBlobs],
        stamps: Callable[[Sequence[Document]], _DateStamps],
        load: Callable[[], tuple[list[Document], list[LoadProblem]]],
    ) -> tuple[list[Document], list[LoadProblem]]:
        """キャッシュが新しければキャッシュを、古ければファイルを再読み込みしてキャッシュする。"""
        with self._lock:
            cached = self._revision_files.get(key)
        if cached is not None and _revision_fresh(
            cached, blob, body_blobs(cached[3]), stamps(cached[3])
        ):
            return cached[3], cached[4]
        found, issues = load()
        with self._lock:
            self._revision_files[key] = (blob, body_blobs(found), stamps(found), found, issues)
        return found, issues

    def _collected_files(
        self,
        key: tuple[Path, str, str, str],
        root: Path,
        table: DocumentTable,
        files: Sequence[str],
    ) -> list[str]:
        """同じ commit と行の定義のファイルの収集の結果を使い回す（無ければ集めて記録する）。"""
        with self._lock:
            collected = self._collected.get(key)
        if collected is None:
            collected = list(collect_files(root, table, files=files))
            with self._lock:
                self._collected[key] = collected
        return collected

    def _discard_revisions(
        self, owner: tuple[Path, str], table_id: str, seen: set[str], table_hash: str
    ) -> None:
        """配信元の行のキャッシュのうち、読んだファイルに無いものと行の定義が変わったものを捨てる。"""
        with self._lock:
            for key in [
                key
                for key in self._revision_files
                if key[:2] == owner
                and key[3] == table_id
                and (key[2] not in seen or key[4] != table_hash)
            ]:
                del self._revision_files[key]

    def _discard_files(self, root: Path, kind_ids: set[str], seen_keys: set[_FileKey]) -> None:
        """作業ツリーから消えたファイルのキャッシュを捨てる。"""
        with self._lock:
            for key in [
                key
                for key in self._files
                if key[1] in kind_ids and key not in seen_keys and key[0].is_relative_to(root)
            ]:
                del self._files[key]

    def load(
        self,
        target: Target,
        *,
        kinds: Sequence[str] | None = None,
        files: Sequence[str] | None = None,
        from_blobs: bool = False,
    ) -> LoadResult:
        """読む場所の文書を、文書の行ごとに集めて返す。

        `files` は呼び出し元が読むフォルダを `walk_files` でたどったパス。
        無ければここで 1 回だけたどり、行ごとにたどり直さない。
        `from_blobs` は、`ref` のある読む場所を書き出さずに commit の blob から読む（`files` を渡したときは使わない）。
        """
        revision = None if target.ref is None else self._commit_of(target)
        tables = self._tables(target, kinds)
        # 書き出さずに読む: commit のファイルの一覧から、たどるパスを選んで blob を読む
        if revision is not None and from_blobs and files is None:
            source = target.source
            reader = self._blob_reader(source.repo_root or source.root)
            commit_files = self._commit_files(target, revision)
            return self._load_walked(
                target, source.root, tables, revision, commit_files, reader=reader
            )
        root = target.base if revision is None else self._revision_root(target, revision)
        # ワークツリーを読む: ワークツリーごとの排他の中で、たどった結果を使い回す
        if revision is None and target.worktree is not None and files is None:
            with self._worktree_lock(root):
                return self._load_worktree(target, root, tables)
        return self._load_walked(target, root, tables, revision, files)

    def _worktree_lock(self, root: Path) -> threading.Lock:
        """ワークツリーごとの排他を返す（無ければ作る）。"""
        with self._lock:
            return self._worktree_locks.setdefault(root, threading.Lock())

    def _load_worktree(self, target: Target, root: Path, tables: list[DocumentTable]) -> LoadResult:
        """ワークツリーの文書を、たどった結果を使い回して集める（ワークツリーごとの排他の中で呼ぶ）。"""
        started = time.monotonic()
        with self._lock:
            walk = self._worktrees.pop(root, None)
            # 使った順の末尾へ移す（上限を超えたら先頭から捨てる）
            if walk is not None:
                self._worktrees[root] = walk
        cold = walk is None
        # 初めて読む・フォルダの中のファイルが増減した: たどり直す
        if walk is None or not _folders_fresh(root, walk.folders):
            files, folders = walk_tree(root)
            walk = _WorktreeWalk(files=files, folders=folders, collected={})
        collected: dict[str, list[str]] = {}
        for table in tables:
            key = _table_hash(table)
            if key not in walk.collected:
                walk.collected[key] = list(collect_files(root, table, files=walk.files))
            collected[table.id] = walk.collected[key]
        result = self._load_walked(target, root, tables, None, walk.files, collected)
        # 読み込みを終えてから記録し、読み込み中のワークツリーを読み込み済みとみなさない
        with self._lock:
            self._worktrees.pop(root, None)
            self._worktrees[root] = walk
            # 上限を超えたら、古く使ったワークツリーの記録から捨てる
            while len(self._worktrees) > WORKTREE_KEEP:
                dropped = next(iter(self._worktrees))
                del self._worktrees[dropped]
                self._worktree_locks.pop(dropped, None)
        if cold:
            logger.info(
                "ワークツリーを読み込んだ（%s・%s・%.1f 秒）",
                target.source.id,
                root,
                time.monotonic() - started,
            )
        return result

    def _load_walked(
        self,
        target: Target,
        root: Path,
        tables: list[DocumentTable],
        revision: str | None,
        files: Sequence[str] | None,
        collected: dict[str, list[str]] | None = None,
        *,
        reader: BlobReader | None = None,
    ) -> LoadResult:
        """読むフォルダのファイルから、文書の行ごとに文書を集める（`reader` があれば commit の blob から読む）。"""
        dates = self._file_dates(target, revision)
        walked = list(walk_files(root)) if files is None else files
        documents: list[Document] = []
        problems: list[LoadProblem] = []
        kind_ids = {table.id for table in tables}
        seen_keys: set[_FileKey] = set()
        for table in tables:
            if revision is None:
                found, issues, seen = self._load_table(
                    root,
                    table,
                    target.source.id,
                    dates,
                    walked,
                    None if collected is None else collected[table.id],
                )
                seen_keys |= seen
            else:
                found, issues = self._load_revision_table(
                    target, root, table, dates, walked, revision, reader
                )
            documents.extend(found)
            problems.extend(issues)
        # 削除されたファイルのキャッシュを捨てる
        self._discard_files(root, kind_ids, seen_keys)
        duplicates: list[Document] = []
        unique = _unique(documents, problems, duplicates)
        problems.sort(key=lambda problem: problem.path)
        for problem in problems:
            logger.debug("%s: %s: %s", target.source.id, problem.path, problem.reason)
        return LoadResult(documents=unique, problems=problems, duplicates=duplicates)

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
            return self._startup_schema(source, table)
        startup = source.schemas.get(kind, {})
        # スキーマは設定ファイルのフォルダからの相対パスなので、root からの相対パスにして読む
        schema_path = source.config_path(table.schema_path)
        base = source.root / schema_path
        if target.ref is not None:
            return self._revision_schema(target, schema_path, startup, base)
        path = self.read_root(target) / schema_path
        try:
            stat = path.stat()
        except OSError:
            return self._startup_schema(source, table)
        with self._lock:
            cached = self._schemas.get(path)
        if cached is not None and cached[:2] == (stat.st_mtime_ns, stat.st_size):
            return cached[2]
        try:
            raw = load_yaml(path.read_text(encoding="utf-8"), file=str(path))
        except OSError, UnicodeDecodeError, YamlLoadError:
            return self._startup_schema(source, table)
        if not is_dict(raw):
            return self._startup_schema(source, table)
        # YAML から読んだ辞書のキーは文字列として扱う
        resolved = resolve_schema_refs(cast("dict[str, Any]", raw), path)
        with self._lock:
            self._schemas[path] = (stat.st_mtime_ns, stat.st_size, resolved)
        return resolved

    def _startup_schema(self, source: ServedSource, table: DocumentTable) -> dict[str, Any]:
        """起動時のスキーマの `$ref` を解いた結果を、配信元と行の定義ごとに 1 回だけ作って返す。"""
        # ワークツリーの設定で作り直した配信元は、行の定義（`schema` の `ref` など）が違えば別のキーになる
        key = (source.id, table.id, _table_hash(table))
        with self._lock:
            cached = self._startup_schemas.get(key)
            generation = self._generation
        if cached is not None:
            return cached
        resolved = startup_schema(source, table)
        with self._lock:
            # 解いている間に `clear` された: 古い配信元のスキーマかもしれないので記録しない
            if generation == self._generation:
                self._startup_schemas[key] = resolved
        return resolved

    def _revision_schema(
        self, target: Target, schema_path: str, startup: dict[str, Any], base: Path
    ) -> dict[str, Any]:
        """リビジョンの種類のスキーマを、commit とスキーマのファイルの相対パスでキャッシュして返す。"""
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
        item = records_item_schema(schema, records)
        if item is None:
            return {}
        # 要素の中に残った `#/$defs/...` の参照先を辿れるよう、最上位の `$defs` を残す
        defs = schema.get("$defs")
        return {**item, "$defs": defs} if defs is not None else item

    def has_worktree(self, target: Target) -> bool:
        """読む場所のワークツリーを一度でも読み込み終えたかを返す（ファイルの `stat` をしない）。"""
        with self._lock:
            return target.base in self._worktrees

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
            self._startup_schemas.clear()
            self._worktrees.clear()
            self._generation += 1


def _revision_fresh(
    cached: _CachedRevisionFile, blob: str, bodies: _BodyBlobs, stamps: _DateStamps
) -> bool:
    """リビジョンのファイルのキャッシュが、blob・本文の blob・日時とも変わらず、本文のファイルの欠けも無いか。"""
    return (
        cached[0] == blob
        and not any(issue.reason == "missing_body_file" for issue in cached[4])
        and cached[1] == bodies
        and cached[2] == stamps
    )


def _unique(
    documents: list[Document], problems: list[LoadProblem], duplicates: list[Document]
) -> list[Document]:
    """ID が先の文書と重なる文書を除き、重なりを `problems` に、除いた文書を `duplicates` に足す。"""
    first: dict[str, Document] = {}
    unique: list[Document] = []
    for document in documents:
        earlier = first.get(document.id)
        if earlier is None:
            first[document.id] = document
            unique.append(document)
            continue
        problems.append(
            LoadProblem(
                path=document.path,
                reason="duplicate_id",
                detail=f"ID {document.id} は先の文書（{earlier.path}）と重なります",
            )
        )
        duplicates.append(document)
    return unique


def _shared_files(
    source: ServedSource, result: LoadResult, files: list[str]
) -> dict[str, list[str]]:
    """2 つ以上の有効な行が文書にするファイルと、その行の ID（`documents[]` の順）を返す。"""
    rows: dict[str, list[str]] = {}
    for table in source.config.documents:
        if not table.enabled:
            continue
        for path in _row_files(source, table, result, files):
            ids = rows.setdefault(path, [])
            if table.id not in ids:
                ids.append(table.id)
    return {path: ids for path, ids in sorted(rows.items()) if len(ids) > 1}


def _duplicate_ids(result: LoadResult, shared: Collection[str]) -> list[str]:
    """ID が先の文書と重なり除外した文書を、先の文書との組で返す（同じファイルの重なりに数えたものを除く）。"""
    first = {document.id: document for document in result.documents}
    pairs: list[str] = []
    for document in sorted(result.duplicates, key=lambda duplicate: duplicate.path):
        earlier = first[document.id]
        earlier_file = earlier.body_path or earlier.path
        document_file = document.body_path or document.path
        # 別の行が同じファイルを文書にした重なりは duplicate_files が示すため数えない
        if (
            earlier.kind != document.kind
            and earlier_file == document_file
            and document_file in shared
        ):
            continue
        pairs.append(
            f"{document.id}: {earlier.kind}（{earlier_file}）・{document.kind}（{document_file}）"
        )
    return pairs


def _row_files(
    source: ServedSource, table: DocumentTable, result: LoadResult, files: list[str]
) -> set[str]:
    """行が文書にするファイル（`body_file` の無い `records` の行は空）を返す。"""
    # 読めず文書にならないファイルも、その行が文書にするファイルに数える
    if table.records is None:
        return set(collect_files(source.root, table, files=files))
    if table.body_file is None:
        return set()
    # ID が重なり除いた文書の本文のファイルも数える
    return {
        document.body_path
        for document in [*result.documents, *result.duplicates]
        if document.kind == table.id and document.body_path
    }


def _unindexed(
    source: ServedSource,
    table: DocumentTable,
    documents: list[Document],
    files: list[str],
    ignored: Collection[str],
) -> list[str]:
    """`records`・`body_file` の行の索引ごとに、索引に無い本文のファイルを集める。"""
    unindexed: list[str] = []
    # その行でない有効な行の文書になるファイルは、索引に無いファイルに数えない
    others = [other for other in source.config.documents if other.enabled and other.id != table.id]
    # 有効な管理用の YAML の行（この行を含む）に当たる管理用の YAML のフォルダ
    index_dirs = {
        posixpath.dirname(path) or "."
        for row in source.config.documents
        if row.enabled and row.records is not None and row.body_file is not None
        for path in collect_files(source.root, row, files=files)
    }
    for index_path in collect_files(source.root, table, files=files):
        body_paths = {
            document.body_path
            for document in documents
            if document.kind == table.id and document.path == index_path and document.body_path
        }
        unindexed.extend(
            f"{table.id}: {path}"
            for path in unindexed_files(
                source.root,
                index_path,
                body_paths,
                table,
                files=files,
                others=others,
                nested_dirs=_nested_dirs(posixpath.dirname(index_path) or ".", index_dirs),
                ignored=ignored,
            )
        )
    return unindexed


def _nested_dirs(start: str, index_dirs: Collection[str]) -> list[str]:
    """`start` より深いフォルダにある管理用の YAML のフォルダを返す。"""
    # 配信元の直下の管理用の YAML: 直下でない全てのフォルダが深い
    if start == ".":
        return [folder for folder in index_dirs if folder != "."]
    # それ以外: `start` の配下のフォルダだけが深い
    return [folder for folder in index_dirs if folder.startswith(f"{start}/")]


def check_sync(store: DocumentStore, source: ServedSource) -> SyncReport:
    """配信元の文書を読み、`metadata` の列の欠け・管理用の YAML のずれ・当たらない関連・同じファイルの重なり・文書の ID の重なり・エイリアスのキーの違反を求める。"""
    # 裏の処理のスレッドでは、手順ごと・要素ごとに裏の処理の 1 件にする（全体を 1 つの 1 件で包まない）
    gate = store.gate
    # 配信元のフォルダは 1 回だけたどり、文書の収集と索引に無いファイルの検出で使い回す
    files = list(gate.each(walk_files(source.root)))
    result = store.load(Target(source, source.root, None, None, "read"), files=files)
    missing_refs = [
        f"{document.kind}: {document.id}: {key}（{field}）"
        for document in gate.each(result.documents)
        for key, field in missing_ref_fields(document.data, source.table(document.kind))
    ]
    # Git の配信元だけ、Git が無視するパスを 1 回だけ求めて索引に無いファイルから除く
    with gate.unit():
        ignored = (ignored_paths(source.root) or []) if source.is_git else []
    unindexed = [
        line
        for table in source.config.documents
        if table.enabled and table.records is not None and table.body_file is not None
        for line in gate.each(_unindexed(source, table, result.documents, files, ignored))
    ]
    missing_body_files = [
        f"{problem.path}: {problem.detail}"
        for problem in result.problems
        if problem.reason == "missing_body_file"
    ]
    # 文書の ID の集合は 1 回だけ作り、全ての文書の関連の照合で使い回す
    with gate.unit():
        ids = {document.id for document in result.documents}
    unresolved = [
        f"{document.kind}: {document.id}: {to}"
        for document in gate.each(result.documents)
        for to in unresolved_related(document.metadata, ids)
    ]
    # 2 つ以上の行が文書にするファイルは、同じファイルの重なりと ID の重なりの除外で使い回す
    with gate.unit():
        shared = _shared_files(source, result, files)
    with gate.unit():
        duplicate_ids = _duplicate_ids(result, shared)
    with gate.unit():
        alias_violations = collect_aliases(source, result.documents).violations
    return SyncReport(
        source_id=source.id,
        missing_refs=missing_refs,
        unindexed_files=unindexed,
        missing_body_files=missing_body_files,
        unresolved_related=unresolved,
        alias_violations=alias_violations,
        duplicate_files=[f"{path}: {'・'.join(ids)}" for path, ids in shared.items()],
        duplicate_ids=duplicate_ids,
    )


# `git ls-tree` のシンボリックリンクのモード
_SYMLINK_MODE = "120000"


def _body_reader(
    reader: BlobReader, blobs: dict[str, str], from_repo: Callable[[str], str]
) -> Callable[[str], str | None]:
    """本文のファイルを同じ commit の blob から読む関数を返す（無い・UTF-8 で読めないなら `None`）。"""

    def read(path: str) -> str | None:
        blob = blobs.get(from_repo(path))
        return None if blob is None else reader.read_text(blob)

    return read


def _documents_from_blob(
    reader: BlobReader,
    blob: str,
    read_body: Callable[[str], str | None],
    root: Path,
    path: str,
    table: DocumentTable,
    *,
    source_id: str,
    dates: dict[str, FileDates],
) -> tuple[list[Document], list[LoadProblem]]:
    """commit のファイルの blob の内容を、文書の行に従って 1 件以上の文書にする。"""
    text = reader.read_text(blob)
    # UTF-8 で読めない: ファイルの読み込みと同じく読めないファイルにする
    if text is None:
        return [], [LoadProblem(path=path, reason="unreadable", detail="UTF-8 で読めません")]
    return documents_from_text(
        text, root, path, table, source_id=source_id, dates=dates, read_body=read_body
    )

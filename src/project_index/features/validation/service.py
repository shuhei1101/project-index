"""文書の検査をまとめて通す。"""

from __future__ import annotations

import dataclasses
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from project_index.features.access.types import Target, script_at
from project_index.features.validation.markdown import (
    MarkdownCheck,
    changed_markdown,
    check_markdown_values,
)
from project_index.features.validation.rules import (
    check_id_format,
    check_related,
    check_schema,
)
from project_index.features.validation.scripts import parse_validator_output
from project_index.integrations.git import run_git
from project_index.integrations.scripts import ScriptError, run_script
from project_index.shared.errors import Violation
from project_index.shared.hashing import value_hash

if TYPE_CHECKING:
    from collections.abc import Mapping

    from project_index.features.documents.store import DocumentStore
    from project_index.features.documents.types import Document
    from project_index.features.sources.schema_ref import SchemaRef
    from project_index.features.sources.types import ScriptEntry
    from project_index.shared.deadline import Deadline

VALIDATOR_ON_READ_CACHE = 4096

# スクリプトの実行で書かれ、スクリプトの状態に含めないフォルダ
_SCRIPT_CACHE_DIR = "__pycache__"

type _ReadKey = tuple[str, str, str, str, str, str, str]
# (基準のフォルダ, `run`, Git の配信元か) → スクリプトの状態
type ScriptStamps = dict[tuple[str, tuple[str, ...], bool], str]

# 状態を取れなかったファイルの更新時刻と大きさ
_UNKNOWN_STAT = -1

__all__ = ["VALIDATOR_ON_READ_CACHE", "DocumentChecker", "run_script"]


def _schema_file(schema_path: str | SchemaRef) -> str:
    """違反に書くスキーマのファイル（ほかの配信元の参照は `{配信元}:{パス}@{リビジョン}`）。"""
    if isinstance(schema_path, str):
        return schema_path
    return f"{schema_path.source}:{schema_path.path}@{schema_path.ref}"


class DocumentChecker:
    """1 件の文書に全ての検査を通し、違反をまとめて返す。"""

    def __init__(self, store: DocumentStore, timeout_sec: float) -> None:
        self.store = store
        self.timeout_sec = timeout_sec
        self._read_cache: OrderedDict[_ReadKey, list[Violation]] = OrderedDict()
        self._lock = threading.Lock()

    def _run_validator(
        self,
        target: Target,
        document: Document,
        validator_id: str,
        deadline: Deadline | None = None,
    ) -> tuple[list[Violation], bool]:
        """検査のスクリプト 1 つを動かし、違反と、動かせたかを返す。"""
        entry = target.source.script("validators", validator_id)
        # 書き込みの期限がある: 過ぎていれば動かさず、制限時間を残りの時間で切る
        if deadline is not None:
            deadline.check()
        timeout_sec = self.timeout_sec if deadline is None else deadline.cap(self.timeout_sec)
        try:
            result = run_script(
                entry.run,
                cwd=target.config_base,
                stdin=document.body,
                timeout_sec=timeout_sec,
                at=script_at(target),
            )
        except ScriptError as error:
            # 期限で止めたスクリプトは、違反ではなく期限の超過にする
            if deadline is not None:
                deadline.check()
            message = " ".join(error.reason.split())
            rule = f"{validator_id}: 検査を実行できませんでした（{message}）"
            return [Violation(path="$", rule=rule)], False
        if deadline is not None:
            deadline.check()
        return parse_validator_output(result.stdout, validator_id=validator_id), True

    def check(
        self,
        target: Target,
        document: Document,
        *,
        on: Literal["read", "write"],
        new: bool = False,
        deadline: Deadline | None = None,
        stamps: ScriptStamps | None = None,
    ) -> list[Violation]:
        """スキーマ・ID の形・関連の種類・`validators[]` を順に通す。"""
        source = target.source
        table = source.table(document.kind)
        violations: list[Violation] = []
        schema = self.store.row_schema(target, document.kind)
        violations.extend(
            check_schema(document.data, schema, schema_file=_schema_file(table.schema_path))
        )
        if new:
            violations.extend(
                check_id_format(document.id, source.config.ids_format, kind=document.kind)
            )
        violations.extend(check_related(document.metadata, source.config.related_types))
        for validator_id in table.validators:
            if on in source.script("validators", validator_id).on:
                violations.extend(
                    self._validate(
                        target, document, validator_id, on=on, deadline=deadline, stamps=stamps
                    )
                )
        return violations

    def _validate(
        self,
        target: Target,
        document: Document,
        validator_id: str,
        *,
        on: Literal["read", "write"],
        deadline: Deadline | None = None,
        stamps: ScriptStamps | None = None,
    ) -> list[Violation]:
        """`validators[]` の 1 行を通す（読み取りの結果は文書・行・スクリプト・参照する場所ごとにキャッシュする）。"""
        # 書き込みの検査はキャッシュしないため、キーを作らない
        key = (
            self._read_key(
                target, document, target.source.script("validators", validator_id), stamps=stamps
            )
            if on == "read"
            else None
        )
        if key is not None:
            with self._lock:
                cached = self._read_cache.get(key)
                if cached is not None:
                    self._read_cache.move_to_end(key)
            if cached is not None:
                return cached
        found, ran = self._run_validator(target, document, validator_id, deadline)
        # 動かせなかった結果はキャッシュしない
        if key is not None and ran:
            with self._lock:
                self._read_cache[key] = found
                while len(self._read_cache) > VALIDATOR_ON_READ_CACHE:
                    self._read_cache.popitem(last=False)
        return found

    def _read_key(
        self,
        target: Target,
        document: Document,
        entry: ScriptEntry,
        *,
        stamps: ScriptStamps | None,
    ) -> _ReadKey:
        """読み取りの `validators[]` の結果をキャッシュするキーを作る。"""
        # 行の全ての項目（`run`・`on` など）が変われば別の結果にする
        entry_hash = value_hash(dataclasses.asdict(entry))
        at = script_at(target)
        # クローン本体で config_commit があればスクリプトはその commit から取り出して動かすため commit で、
        # それ以外（ワークツリー・config_commit の無い配信元）は作業ツリーのスクリプトの状態で区別する
        script_state = at[1] if at is not None else _cached_stamp(target, entry, stamps)
        location = str(target.worktree) if target.worktree is not None else ""
        return (
            target.source.id,
            document.kind,
            entry.id,
            document.version,
            entry_hash,
            script_state,
            location,
        )

    def check_markdown(
        self,
        target: Target,
        document: Document,
        *,
        previous: Mapping[str, Any] | None,
        stopped: str | None = None,
        deadline: Deadline | None = None,
    ) -> MarkdownCheck:
        """書き込む文書の変えた Markdown の値を mdmark の点検に通す。"""
        schema = self.store.row_schema(target, document.kind)
        values = changed_markdown(document.data, previous, schema)
        # Markdown の値を変えていなければ mdmark を呼ばない
        if not values:
            return MarkdownCheck(violations=[], unchecked=[], stopped=stopped)
        return check_markdown_values(
            values,
            cwd=target.base,
            timeout_sec=self.timeout_sec,
            stopped=stopped,
            deadline=deadline,
        )

    def clear(self) -> None:
        """読み取りの結果のキャッシュを捨てる。"""
        with self._lock:
            self._read_cache.clear()


def _cached_stamp(target: Target, entry: ScriptEntry, stamps: ScriptStamps | None) -> str:
    """作業ツリーのスクリプトの状態を、`stamps` にあれば使い回し、無ければ作って入れる。"""
    use_git = target.source.is_git
    memo_key = (str(target.config_base), tuple(entry.run), use_git)
    # 同じ要求の中で作った状態がある: 走査し直さない
    if stamps is not None and memo_key in stamps:
        return stamps[memo_key]
    stamp = _script_stamp(target.config_base, entry.run, use_git=use_git)
    if stamps is not None:
        stamps[memo_key] = stamp
    return stamp


def _script_stamp(base: Path, run: list[str], *, use_git: bool) -> str:
    """`run` が指すファイルのフォルダの配下（`__pycache__` を除く）の `stat` のハッシュを返す。"""
    folders = _script_folders(base, run)
    # 作業ツリーにスクリプトのファイルが無い（コマンドだけの `run`）
    if not folders:
        return ""
    stamps: list[tuple[str, int, int]] = []
    for folder in sorted(folders):
        stamps.extend(_folder_stamps(base, folder, use_git=use_git))
    return value_hash(stamps)


def _script_folders(base: Path, run: list[str]) -> set[Path]:
    """`run` の要素のうち `base` から解いてファイルがあるものの、フォルダを返す。"""
    folders: set[Path] = set()
    for item in run:
        # オプションと絶対パス（インタープリターなど）は作業ツリーのスクリプトではない
        if item.startswith("-") or Path(item).is_absolute():
            continue
        path = base / item
        if path.is_file():
            folders.add(path.parent)
    return folders


def _folder_files(folder: Path, *, use_git: bool) -> list[Path]:
    """フォルダの配下のファイルを、`__pycache__` の配下を除いてパスの順に返す。"""
    # Git の配信元は `git archive` が取り出す範囲、管理外はサブフォルダまで全て
    files = _git_files(folder) if use_git else _walked_files(folder)
    return sorted(
        {path for path in files if _SCRIPT_CACHE_DIR not in path.relative_to(folder).parts}
    )


def _git_files(folder: Path) -> list[Path]:
    """Git が管理するファイルと、追跡していないが無視していないファイルを返す。"""
    output = run_git(
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
        cwd=folder,
    )
    text = output if isinstance(output, str) else output.decode("utf-8")
    return [folder / name for name in text.split("\0") if name]


def _walked_files(folder: Path) -> list[Path]:
    """サブフォルダまでたどったファイルを返す（`__pycache__` のフォルダはたどらない）。"""
    files: list[Path] = []
    for current, dirs, names in os.walk(folder):
        dirs[:] = [name for name in dirs if name != _SCRIPT_CACHE_DIR]
        files.extend(Path(current) / name for name in names)
    return files


def _folder_stamps(base: Path, folder: Path, *, use_git: bool) -> list[tuple[str, int, int]]:
    """フォルダの配下のファイルの (`base` からの相対パス, 更新時刻, 大きさ) をパスの順に返す。"""
    stamps: list[tuple[str, int, int]] = []
    for path in _folder_files(folder, use_git=use_git):
        relative = Path(os.path.relpath(path, base)).as_posix()
        try:
            stat = path.stat()
        except OSError:
            # 列挙の後に消えた・リンク先が無い: 取れなかったことを値にして続ける
            stamps.append((relative, _UNKNOWN_STAT, _UNKNOWN_STAT))
            continue
        stamps.append((relative, stat.st_mtime_ns, stat.st_size))
    return stamps

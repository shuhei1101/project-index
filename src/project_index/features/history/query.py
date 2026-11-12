"""リビジョンの解決・一覧・変わったファイル・ファイルの日時。"""

from __future__ import annotations

import io
import logging
import re
import tarfile
import tempfile
from contextlib import contextmanager
from datetime import datetime, time
from pathlib import Path
from typing import TYPE_CHECKING

from project_index.features.history.types import (
    CommitStep,
    CommitSummary,
    FileChange,
    FileDates,
    NamedRef,
    RefList,
    ResolvedRef,
    WorktreeInfo,
)
from project_index.integrations.git import GitError, run_git
from project_index.shared.errors import RefNotFoundError
from project_index.shared.paths import match_glob

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence

    from project_index.features.sources.types import ServedSource

logger = logging.getLogger(__name__)

SHORT_SHA_LENGTH = 7
CO_CHANGE_COMMITS = 50
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}([T ].*)?$")
QUOTE_OFF = ["-c", "core.quotepath=off"]
NEXT_STEPS = ["`git log` で確認してください"]


def _text(args: Sequence[str], cwd: Path) -> str:
    """git の標準出力を文字列で返す。"""
    output = run_git(args, cwd=cwd)
    return output if isinstance(output, str) else output.decode("utf-8")


def _not_found(argument: str, ref: str) -> RefNotFoundError:
    """リビジョンを解決できないエラーを作る。"""
    return RefNotFoundError(
        message=f"{argument}={ref} を commit に解決できません",
        argument=argument,
        value=ref,
        next_steps=NEXT_STEPS,
    )


def resolve_ref(repo_root: Path, ref: str, *, date_base: str, argument: str = "ref") -> ResolvedRef:
    """ブランチ・タグ・commit・日時を commit とその日時に解く。"""
    if DATE_PATTERN.match(ref):
        # 日付か日時はその時点の最後の commit にする（日付だけならその日の終わり）
        moment = datetime.fromisoformat(ref)
        if len(ref) == len("2026-10-03"):
            moment = datetime.combine(moment.date(), time.max)
        stamp = moment.astimezone().isoformat() if moment.tzinfo is None else moment.isoformat()
        try:
            commit = _text(["rev-list", "-1", f"--before={stamp}", date_base], repo_root).strip()
        except GitError as error:
            raise _not_found(argument, ref) from error
        if not commit:
            raise _not_found(argument, ref)
    else:
        if ref.startswith("-"):
            raise _not_found(argument, ref)
        try:
            commit = _text(
                ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], repo_root
            ).strip()
        except GitError as error:
            raise _not_found(argument, ref) from error
    stamp_text = _text(["show", "-s", "--format=%cI", commit], repo_root).strip()
    return ResolvedRef(input=ref, commit=commit, date=datetime.fromisoformat(stamp_text))


def list_refs(source: ServedSource, *, commits: int = 20) -> RefList:
    """配信元のブランチ・タグ・`default_ref` の最近の commit を返す。"""
    default_ref = source.config.default_ref
    if not source.is_git or source.repo_root is None:
        return RefList(git=False, default_ref=default_ref)
    root = source.repo_root
    output = _text(
        [
            "for-each-ref",
            "--format=%(refname)%00%(objectname:short=7)%00%(*objectname:short=7)",
            "refs/heads",
            "refs/tags",
        ],
        root,
    )
    branches: list[NamedRef] = []
    tags: list[NamedRef] = []
    for line in output.splitlines():
        refname, commit, dereferenced = line.split("\0")
        # 注釈付きタグは指す commit にする
        target = dereferenced or commit
        if refname.startswith("refs/heads/"):
            branches.append(NamedRef(refname.removeprefix("refs/heads/"), target))
        else:
            tags.append(NamedRef(refname.removeprefix("refs/tags/"), target))
    recent: list[CommitSummary] = []
    if commits > 0:
        try:
            log = _text(
                ["log", f"-n{commits}", "--abbrev=7", "--format=%h%x00%cI%x00%s", default_ref],
                root,
            )
        except GitError:
            logger.warning("既定のリビジョンが無い（%s・%s）", source.id, default_ref)
        else:
            for line in log.splitlines():
                short, date, subject = line.split("\0")
                recent.append(CommitSummary(short, date, subject))
    return RefList(git=True, default_ref=default_ref, branches=branches, tags=tags, commits=recent)


def changed_files(
    work_root: Path,
    from_commit: str,
    to_commit: str | None = None,
    *,
    pathspec: str | None = None,
) -> list[FileChange]:
    """2 つの commit の間、または commit と作業ツリーの間で変わったファイルを返す。"""
    args = ["diff", "--name-status", "--no-renames", "-z", from_commit]
    if to_commit is not None:
        args.append(to_commit)
    if pathspec:
        args.extend(["--", pathspec])
    tokens = _text(args, work_root).split("\0")
    changes: dict[str, FileChange] = {}
    # -z の出力は「状態, パス」の組が NUL で並ぶ
    for status, path in zip(tokens[0::2], tokens[1::2], strict=False):
        if not status:
            continue
        kind = {"A": "added", "D": "deleted"}.get(status[0], "modified")
        changes[path] = FileChange(path=path, change=kind)  # type: ignore[arg-type]
    # 作業ツリーとの間では、未追跡のファイルも足したものとして加える
    if to_commit is None:
        untracked = ["ls-files", "--others", "--exclude-standard", "-z"]
        if pathspec:
            untracked.extend(["--", pathspec])
        for path in _text(untracked, work_root).split("\0"):
            if path:
                changes[path] = FileChange(path=path, change="added")
    return [changes[path] for path in sorted(changes)]


def file_dates(
    work_root: Path, *, commit: str = "HEAD", pathspec: str | None = None
) -> dict[str, FileDates]:
    """ファイルごとに最初と最後の commit の日時を 1 回の git で引く。"""
    args = [*QUOTE_OFF, "log", "--format=%x00%cI", "--name-only", "--no-renames", commit]
    if pathspec:
        args.extend(["--", pathspec])
    try:
        output = _text(args, work_root)
    except GitError:
        # commit がまだ 1 つも無いリポジトリ
        return {}
    newest: dict[str, datetime] = {}
    oldest: dict[str, datetime] = {}
    # 新しい commit から順に並ぶので、最初に出た日時が最後の変更、最後に出た日時が最初の変更
    for chunk in output.split("\0")[1:]:
        lines = chunk.splitlines()
        moment = datetime.fromisoformat(lines[0])
        for path in lines[1:]:
            if not path:
                continue
            newest.setdefault(path, moment)
            oldest[path] = moment
    return {path: FileDates(created=oldest[path], updated=newest[path]) for path in newest}


def co_changed_files(
    work_root: Path, paths: Sequence[str], *, max_commits: int = CO_CHANGE_COMMITS
) -> dict[str, int]:
    """起点のファイルと同じ commit で変わったファイルを、一緒に変わった回数で数える。"""
    log = _text(
        [*QUOTE_OFF, "log", f"-n{max_commits}", "--format=%H", "--no-renames", "--", *paths],
        work_root,
    )
    commits = [line for line in log.splitlines() if line]
    if not commits:
        return {}
    shown = _text(
        [*QUOTE_OFF, "show", "--format=", "--name-only", "--no-renames", *commits], work_root
    )
    counts: dict[str, int] = {}
    for path in shown.splitlines():
        if path and path not in paths:
            counts[path] = counts.get(path, 0) + 1
    return counts


def read_file_at(work_root: Path, commit: str, path: str) -> str | None:
    """commit のあるファイルを書き出さずに読む。"""
    try:
        output = run_git(["show", f"{commit}:{path}"], cwd=work_root, binary=True)
    except GitError:
        return None
    return output.decode("utf-8") if isinstance(output, bytes) else output


def list_commits(work_root: Path, from_commit: str, to_ref: str) -> list[CommitStep]:
    """区間の中の commit（マージ commit を除く）を、最初の親と一緒に古い順に並べる。"""
    log = _text(
        [
            "log",
            "--no-merges",
            "--reverse",
            "--format=%H%x00%cI%x00%P",
            f"{from_commit}..{to_ref}",
        ],
        work_root,
    )
    rows = [line.split("\0") for line in log.splitlines() if line]
    # 親が無い root の commit は、親と比べられないので除く
    rows = [row for row in rows if row[2].strip()]
    if not rows:
        return []
    parents = {row[2].split()[0] for row in rows}
    shown = _text(["show", "-s", "--format=%H%x00%cI", *sorted(parents)], work_root)
    parent_dates = {
        commit: datetime.fromisoformat(moment)
        for commit, moment in (line.split("\0") for line in shown.splitlines() if line)
    }
    return [
        CommitStep(
            commit=row[0],
            date=datetime.fromisoformat(row[1]),
            parent=row[2].split()[0],
            parent_date=parent_dates[row[2].split()[0]],
        )
        for row in rows
    ]


def list_worktrees(source: ServedSource) -> list[WorktreeInfo]:
    """配信元の `worktrees` に当たるワークツリーのパスと checkout しているブランチを返す。"""
    if not source.is_git or source.repo_root is None:
        return []
    output = _text(["worktree", "list", "--porcelain"], source.repo_root)
    result: list[WorktreeInfo] = []
    # 空行で区切ったかたまりが 1 つのワークツリー
    for chunk in output.split("\n\n"):
        path: str | None = None
        branch: str | None = None
        for line in chunk.splitlines():
            if line.startswith("worktree "):
                path = line.removeprefix("worktree ")
            elif line.startswith("branch "):
                branch = line.removeprefix("branch ").removeprefix("refs/heads/")
        if path is not None and match_glob(Path(path), source.worktree_globs):
            result.append(WorktreeInfo(path=path, branch=branch))
    return result


@contextmanager
def export_paths_at(repo: Path, commit: str, paths: Sequence[str]) -> Generator[Path]:
    """commit のリビジョンのフォルダを一時フォルダへ取り出し、抜けるときに削除する。"""
    with tempfile.TemporaryDirectory() as directory:
        output = run_git(["archive", "--format=tar", commit, "--", *paths], cwd=repo, binary=True)
        data = output if isinstance(output, bytes) else output.encode("utf-8")
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(directory, filter="data")
        yield Path(directory)

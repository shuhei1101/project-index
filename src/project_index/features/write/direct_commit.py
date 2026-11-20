"""直コミットの書き込む先の決定と、取得・確認・コミット・プッシュ・照合・戻し。"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from project_index.features.access.service import base_of, find_worktree
from project_index.features.write.types import CommitResult
from project_index.integrations.git import GitError, run_git, worktree_heads
from project_index.shared.errors import (
    BranchNotAllowedError,
    CommitWorktreeNotFoundError,
    DirectCommitNotConfiguredError,
    FetchFailedError,
    PushFailedError,
    PushRejectedError,
    UncommittedChangesError,
    UnpushedCommitsError,
    WriteDeadlineExceededError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from project_index.features.sources.types import ServedSource
    from project_index.features.write.types import CommitSpec
    from project_index.shared.deadline import CallLimits

logger = logging.getLogger(__name__)

# プッシュを止めた後の照合・戻し・応答の組み立てに残す秒数（NFR-15）
DIRECT_COMMIT_MARGIN_SEC = 8
# 生成の制限時間から除くプッシュの秒数（NFR-16）
DIRECT_COMMIT_PUSH_SEC = 5
# 取得とプッシュをするリモート（呼び出しで上書きしない）
REMOTE = "origin"
# 1 回の直コミットでプッシュを試す回数（断られたら 1 回だけやり直す）
PUSH_ATTEMPTS = 2
# `status --porcelain=v1` の 1 行のうち、パスの前の状態の 2 文字と空白の長さ
STATUS_PREFIX_LEN = 3

type PushState = Literal["pushed", "rejected", "failed", "unknown"]


@dataclass(frozen=True, slots=True, kw_only=True)
class CommitPlan:
    """1 回の直コミットの配信元・ブランチ・ワークツリー・リポジトリ・説明。"""

    source_id: str
    branch: str
    # ブランチを HEAD が指すワークツリーの直下
    worktree: Path
    # `git rev-parse --git-common-dir` の絶対パス。排他の単位
    repo: Path
    message: str
    # ワークツリーの中の配信元のフォルダ。生成物とみなすパスの範囲
    base: Path


@dataclass(frozen=True, slots=True, kw_only=True)
class DirtyFiles:
    """書き込みの前にワークツリーにあった未コミットの変更のパスと内容のハッシュ。"""

    # ワークツリーの直下からのパス → 内容のハッシュ（削除されたファイルは `None`）
    hashes: dict[str, str | None]


@dataclass(frozen=True, slots=True, kw_only=True)
class PushOutcome:
    """プッシュの結果と、失敗したときの理由。"""

    state: PushState
    reason: str = ""


def resolve_commit_plan(source: ServedSource, commit: CommitSpec) -> CommitPlan:
    """配信元の直コミットの設定と `commit` から、ブランチとそのワークツリーを決める。"""
    settings = source.config.direct_commit
    # 直コミットを使用できない配信元は断る
    reason = _not_configured_reason(source)
    if reason is not None or settings is None or source.repo_root is None:
        raise DirectCommitNotConfiguredError(
            message=f"{source.id} は直コミットを使用できません: {reason or '直コミットの設定が無い'}",
            source_id=source.id,
            reason=reason or "直コミットの設定が無い",
            next_steps=["配信元の設定の direct_commit と、端末の設定の storage を確認してください"],
        )
    branch = commit.branch or settings.branch
    # 既定のブランチでも上書きできるブランチでもなければ断る
    if branch != settings.branch and not any(
        fnmatch.fnmatchcase(branch, pattern) for pattern in settings.branches
    ):
        raise BranchNotAllowedError(
            message=(
                f"{branch} は {source.id} の直コミットで上書きできないブランチです"
                f"（上書きできるブランチ: {', '.join([settings.branch, *settings.branches])}）"
            ),
            branch=branch,
            allowed=[settings.branch, *settings.branches],
            next_steps=[
                "commit.branch を省くか、direct_commit.branches のブランチを指定してください"
            ],
        )
    worktree = _branch_worktree(source, source.repo_root, branch)
    repo = Path(
        _text(
            run_git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=worktree)
        ).strip()
    )
    return CommitPlan(
        source_id=source.id,
        branch=branch,
        worktree=worktree,
        repo=repo,
        message=commit.message,
        base=base_of(source, worktree),
    )


def sync_worktree(plan: CommitPlan, *, timeout: float) -> str:
    """リモートのブランチを取得して早送りで取り込み、HEAD がリモートの追跡ブランチと同じことを確かめる。"""
    # 書き込みの期限を過ぎていれば取得を始めない
    if timeout <= 0:
        raise WriteDeadlineExceededError(
            message="書き込みの期限を超えたため、ファイルを書き換えずに止めました（経過 0 秒）",
            next_steps=["時間を置いてから再実行してください"],
        )
    remote_ref = f"{REMOTE}/{plan.branch}"
    try:
        run_git(["fetch", REMOTE, plan.branch], cwd=plan.worktree, timeout=timeout)
    except GitError as error:
        raise FetchFailedError(
            message=f"{REMOTE} の {plan.branch} を取得できません: {error.stderr}",
            stderr=error.stderr,
            next_steps=["リモートへの接続と認証を確認してから再実行してください"],
        ) from error
    try:
        run_git(["merge", "--ff-only", remote_ref], cwd=plan.worktree)
    except GitError as error:
        # 未コミットの変更が取り込む変更と重なる
        if "would be overwritten" in error.stderr or "commit your changes" in error.stderr:
            paths = [line.strip() for line in error.stderr.splitlines() if line.startswith("\t")]
            raise UncommittedChangesError(
                message=f"コミットしていない変更があるため取り込めません: {', '.join(paths)}",
                paths=paths,
                next_steps=["ワークツリーの変更をコミットするか戻してから再実行してください"],
            ) from error
        # それ以外は早送りで取り込めない（ローカルとリモートが分かれた）
        raise UnpushedCommitsError(
            message=f"{plan.worktree} を早送りで取り込めません: {error.stderr}",
            worktree=str(plan.worktree),
            next_steps=["ワークツリーのコミットをプッシュするか戻してから再実行してください"],
        ) from error
    counts = _text(
        run_git(["rev-list", "--left-right", "--count", f"HEAD...{remote_ref}"], cwd=plan.worktree)
    ).split()
    ahead, behind = int(counts[0]), int(counts[1])
    # HEAD が追跡ブランチと違えば、プッシュしていないコミットがある
    if (ahead, behind) != (0, 0):
        raise UnpushedCommitsError(
            message=f"{plan.worktree} にプッシュしていないコミットがあります（先行 {ahead}・遅延 {behind}）",
            worktree=str(plan.worktree),
            ahead=ahead,
            behind=behind,
            next_steps=["ワークツリーのコミットをプッシュするか戻してから再実行してください"],
        )
    return _head(plan)


def snapshot_dirty(plan: CommitPlan) -> DirtyFiles:
    """書き込みの前のワークツリーの未コミットの変更のパスと内容のハッシュを控える。"""
    output = _text(
        run_git(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames"],
            cwd=plan.worktree,
        )
    )
    hashes: dict[str, str | None] = {}
    # 1 行は `XY パス`。-z なのでパスはそのままの文字で NUL で区切られる
    for entry in output.split("\0"):
        # 状態の 2 文字と空白の後にパスが続く。空の区切りは飛ばす
        if len(entry) <= STATUS_PREFIX_LEN:
            continue
        path = entry[STATUS_PREFIX_LEN:]
        hashes[path] = _file_hash(plan.worktree / path)
    return DirtyFiles(hashes=hashes)


def check_clean(dirty: DirtyFiles, paths: Iterable[str]) -> None:
    """これから書き込むファイルに未コミットの変更が無いことを確かめる。"""
    found = sorted({path for path in paths if path in dirty.hashes})
    if found:
        raise UncommittedChangesError(
            message=f"コミットしていない変更があるファイルには書き込めません: {', '.join(found)}",
            paths=found,
            next_steps=["ワークツリーの変更をコミットするか戻してから再実行してください"],
        )


def changed_paths(
    plan: CommitPlan, before: DirtyFiles, written: list[Path]
) -> tuple[list[str], list[str]]:
    """この呼び出しが書き換えたパスと、利用者の変更と見分けられないパスを求める。"""
    after = snapshot_dirty(plan)
    touched = {path.relative_to(plan.worktree).as_posix() for path in written}
    unknown: set[str] = set()
    for path, digest in after.hashes.items():
        # 配信元のフォルダの外の差は、他のツール・エディタの変更として含めない
        if not _in_base(plan, path):
            continue
        if path not in before.hashes:
            touched.add(path)
        elif before.hashes[path] != digest:
            unknown.add(path)
    return sorted(touched - unknown), sorted(unknown)


def commit_written(
    plan: CommitPlan, before: DirtyFiles, written: list[Path]
) -> tuple[str, list[str]]:
    """操作が書き込んだファイルと生成物だけをコミットする。"""
    paths, unknown = changed_paths(plan, before, written)
    # 生成が未コミットの変更のあるファイルを書き換えた
    if unknown:
        raise UncommittedChangesError(
            message=f"コミットしていない変更があるファイルを生成が書き換えました: {', '.join(unknown)}",
            paths=unknown,
            next_steps=["ワークツリーの変更をコミットするか戻してから再実行してください"],
        )
    # 書き換えたファイルが無ければコミットしない（HEAD をそのままプッシュする）
    if not paths:
        return _head(plan), []
    run_git(["add", "-A", "--", *paths], cwd=plan.worktree)
    # 他にステージされた変更をコミットに含めない
    run_git(["commit", "--only", "-m", plan.message, "--", *paths], cwd=plan.worktree)
    return _head(plan), paths


def push_commit(plan: CommitPlan, sha: str, *, timeout: float) -> PushOutcome:
    """コミットをプッシュし、断られた以外の失敗はリモートを取得し直して届いたかを照合する。"""
    # 時間が残っていなければプッシュを始めない
    if timeout <= 0:
        return PushOutcome(state="failed", reason="プッシュの時間が残っていない")
    try:
        run_git(
            ["push", "--porcelain", REMOTE, f"HEAD:refs/heads/{plan.branch}"],
            cwd=plan.worktree,
            timeout=timeout,
        )
    except GitError as error:
        rejected = [line for line in error.stdout.splitlines() if line.startswith("!")]
        # リモートに断られた
        if rejected:
            return PushOutcome(state="rejected", reason=f"{rejected[0]}\n{error.stderr}".strip())
        # 通信の失敗・制限時間で止めた: 届いたかを照合する
        return _verify_push(plan, sha, error.stderr)
    return PushOutcome(state="pushed")


def rollback(plan: CommitPlan, base: str, paths: list[str]) -> None:
    """作ったコミットを取り消し、書き込んだファイルと生成物を書き込みの前の内容に戻す。"""
    # HEAD だけを戻し、他の未コミットの変更とステージは残す
    if _head(plan) != base:
        run_git(["reset", "--soft", base], cwd=plan.worktree)
    for path in paths:
        # 基点にあるパスはインデックスと作業ツリーを基点の内容にする
        if _exists_at(plan, base, path):
            run_git(["checkout", base, "--", path], cwd=plan.worktree)
            continue
        # 基点に無いパスはインデックスから外してファイルを消す
        run_git(["rm", "--cached", "--ignore-unmatch", "--quiet", "--", path], cwd=plan.worktree)
        (plan.worktree / path).unlink(missing_ok=True)


def run_direct_commit(
    plan: CommitPlan,
    write_once: Callable[[DirtyFiles], list[Path]],
    *,
    limits: CallLimits,
) -> CommitResult:
    """取り込み・書き込み・コミット・プッシュを進め、断られたら 1 回だけやり直す。"""
    reason = ""
    for attempt in range(1, PUSH_ATTEMPTS + 1):
        base = sync_worktree(plan, timeout=limits.write_deadline.remaining())
        before = snapshot_dirty(plan)
        written = _write_or_rollback(plan, base, before, write_once)
        try:
            sha, paths = commit_written(plan, before, written)
        except Exception:
            touched, _ = changed_paths(plan, before, written)
            rollback(plan, base, touched)
            raise
        outcome = push_commit(
            plan, sha, timeout=limits.respond_by.remaining() - DIRECT_COMMIT_MARGIN_SEC
        )
        # 届いた
        if outcome.state == "pushed":
            return CommitResult(sha=sha, branch=plan.branch, retried=attempt > 1)
        rollback(plan, base, paths)
        # 届かない・結果が不明
        if outcome.state != "rejected":
            raise _push_failed(plan, sha, outcome)
        reason = outcome.reason
        logger.warning("直コミットのプッシュが断られた（%s・%s 回目）", plan.branch, attempt)
        # やり直す前に書き込みの期限を過ぎていれば、やり直さない
        if limits.write_deadline.remaining() <= 0:
            break
    raise PushRejectedError(
        message=f"{plan.branch} へのプッシュが断られました: {reason}",
        reason=reason,
        next_steps=["リモートのブランチの保護の規則と、同時に書き込んでいる作業を確認してください"],
    )


def _write_or_rollback(
    plan: CommitPlan,
    base: str,
    before: DirtyFiles,
    write_once: Callable[[DirtyFiles], list[Path]],
) -> list[Path]:
    """書き込みを呼び、例外ならこの呼び出しが書き換えたパスを戻してから送り直す。"""
    try:
        return write_once(before)
    except Exception as error:
        touched, unknown = changed_paths(plan, before, [])
        # 利用者の変更と見分けられないパスがあれば戻さない
        if unknown:
            raise UncommittedChangesError(
                message=f"書き込みの失敗の後に戻せないファイルがあります: {', '.join(unknown)}",
                paths=unknown,
                next_steps=["ワークツリーの変更を確認してください"],
            ) from error
        if touched:
            rollback(plan, base, touched)
        raise


def _push_failed(plan: CommitPlan, sha: str, outcome: PushOutcome) -> PushFailedError:
    """届かない・結果が不明のプッシュのエラーを作る。"""
    unknown = outcome.state == "unknown"
    detail = f"結果は不明です（{sha}）" if unknown else outcome.reason
    return PushFailedError(
        message=f"{plan.branch} へプッシュできませんでした: {detail}",
        stderr=outcome.reason,
        unknown=unknown,
        commit=sha if unknown else "",
        next_steps=["リモートへの接続を確認してから再実行してください"],
    )


def _verify_push(plan: CommitPlan, sha: str, stderr: str) -> PushOutcome:
    """リモートを取得し直し、コミットが届いたかを照合する。"""
    try:
        run_git(
            ["fetch", REMOTE, plan.branch], cwd=plan.worktree, timeout=DIRECT_COMMIT_MARGIN_SEC / 2
        )
    except GitError as error:
        return PushOutcome(state="unknown", reason=f"{stderr}\n{error.stderr}".strip())
    try:
        run_git(["merge-base", "--is-ancestor", sha, f"{REMOTE}/{plan.branch}"], cwd=plan.worktree)
    except GitError:
        return PushOutcome(state="failed", reason=stderr)
    return PushOutcome(state="pushed")


def _not_configured_reason(source: ServedSource) -> str | None:
    """直コミットを使用できない理由を返す（使用できれば `None`）。"""
    if source.config.direct_commit is None:
        return "直コミットの設定が無い"
    if source.storage == "disk" or not source.is_git:
        return "disk の配信元である"
    if source.direct_commit_problems:
        return "; ".join(f"{item.path}: {item.rule}" for item in source.direct_commit_problems)
    return None


def _branch_worktree(source: ServedSource, repo_root: Path, branch: str) -> Path:
    """ブランチを HEAD が指す配信元のワークツリーを返す（無ければ送る）。"""
    for path, head in worktree_heads(repo_root):
        if head == branch and find_worktree(source, path) is not None:
            return path
    raise CommitWorktreeNotFoundError(
        message=f"{branch} を指すワークツリーがありません",
        branch=branch,
        next_steps=[f"配信元の worktrees に当たる場所へ {branch} のワークツリーを作ってください"],
    )


def _in_base(plan: CommitPlan, path: str) -> bool:
    """ワークツリーの直下からのパスが、配信元のフォルダの配下かを返す。"""
    return (plan.worktree / path).is_relative_to(plan.base)


def _exists_at(plan: CommitPlan, revision: str, path: str) -> bool:
    """パスがリビジョンにあるかを返す。"""
    try:
        run_git(["cat-file", "-e", f"{revision}:{path}"], cwd=plan.worktree)
    except GitError:
        return False
    return True


def _head(plan: CommitPlan) -> str:
    """ワークツリーの HEAD の SHA を返す。"""
    return _text(run_git(["rev-parse", "HEAD"], cwd=plan.worktree)).strip()


def _file_hash(path: Path) -> str | None:
    """ファイルの内容のハッシュを返す（無ければ `None`）。"""
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(output: str | bytes) -> str:
    """git の標準出力を文字列にする。"""
    return output if isinstance(output, str) else output.decode("utf-8")

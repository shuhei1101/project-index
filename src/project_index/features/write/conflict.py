"""書き込みの API が衝突したときの、編集を始めたときのコミットの確認・ブランチへのコミット・スクリプトの実行。"""

from __future__ import annotations

import logging
import shutil
import tempfile
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

from project_index.features.write.direct_commit import DIRECT_COMMIT_MARGIN_SEC, REMOTE
from project_index.features.write.types import ScriptRunResult
from project_index.integrations.git import GitError, run_git
from project_index.integrations.scripts import (
    ScriptFailedError,
    ScriptNotFoundError,
    ScriptTimeoutError,
    run_script,
)
from project_index.shared.errors import (
    BaseCommitUnusableError,
    DocumentNotFoundError,
    DocumentReferencedError,
    ValidationFailedError,
    VersionMismatchError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import datetime

    from project_index.features.settings.types import OnConflictScript
    from project_index.features.write.direct_commit import CommitPlan
    from project_index.shared.deadline import Deadline

logger = logging.getLogger(__name__)

# 衝突したときに作るブランチの名前の頭
CONFLICT_BRANCH_PREFIX = "project-index/conflict/"
# 応答に入れる衝突したときのスクリプトの標準出力・標準エラー出力の末尾の文字数
SCRIPT_OUTPUT_TAIL_CHARS = 8000
# 今のブランチでこの例外で断られた要求を衝突にする
CONFLICT_ERRORS = (
    VersionMismatchError,
    DocumentNotFoundError,
    DocumentReferencedError,
    ValidationFailedError,
)


def verify_base_commit(base_commit: str, *, plan: CommitPlan, timeout: float) -> str:
    """`baseCommit` がクローンにあり、コミットするブランチの祖先であることを確認して 40 桁の SHA を返す。"""
    # クローンにコミットがあるか
    try:
        sha = str(
            run_git(
                ["rev-parse", "--verify", "--quiet", f"{base_commit}^{{commit}}"],
                cwd=plan.worktree,
                timeout=timeout,
            )
        ).strip()
    except GitError as error:
        raise BaseCommitUnusableError(
            message=f"編集を始めたときのコミット {base_commit} がクローンにありません",
            next_steps=["文書を取得し直して、編集を始めたときのコミットを指定し直してください"],
            base_commit=base_commit,
            reason="not_found",
        ) from error
    # コミットするブランチの祖先か（終了コード 1 は祖先でない）
    try:
        run_git(
            ["merge-base", "--is-ancestor", sha, f"{REMOTE}/{plan.branch}"],
            cwd=plan.worktree,
            timeout=timeout,
        )
    except GitError as error:
        if error.returncode != 1:
            raise
        raise BaseCommitUnusableError(
            message=f"編集を始めたときのコミット {base_commit} は {plan.branch} の祖先ではありません",
            next_steps=["文書を取得し直して、編集を始めたときのコミットを指定し直してください"],
            base_commit=base_commit,
            reason="not_ancestor",
        ) from error
    return sha


def conflict_branch_name(commit: str, *, now: datetime) -> str:
    """コミットと時刻から衝突したときのブランチの名前を組み立てる。"""
    stamp = now.astimezone(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{CONFLICT_BRANCH_PREFIX}{stamp}-{commit[:7]}"


def keep_in_branch(
    plan: CommitPlan,
    *,
    base_sha: str,
    write_once: Callable[[Path], list[Path]],
    state_dir: Path,
    commit: bool,
    now: datetime,
    timeout: float,
    respond_by: Deadline,
) -> tuple[str, str] | None:
    """編集を始めたときのコミットの一時のワークツリーで書き込みを当ててコミットし、そのコミットにブランチを作る。"""
    parent = state_dir / "conflicts"
    parent.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(dir=parent))
    try:
        run_git(
            ["worktree", "add", "--detach", str(folder), base_sha],
            cwd=plan.worktree,
            timeout=timeout,
        )
        # ワークツリーの中の配信元のフォルダを、一時のワークツリーに重ねる
        source_folder = folder / plan.base.relative_to(plan.worktree)
        written = write_once(source_folder)
        # 試しに書く: コミットとブランチを作らない
        if not commit:
            return None
        paths = [str(path.relative_to(folder)) for path in written]
        run_git(["add", "-A", "--", *paths], cwd=folder, timeout=_commit_timeout(respond_by))
        run_git(
            ["commit", "--only", "-m", plan.message, "--", *paths],
            cwd=folder,
            timeout=_commit_timeout(respond_by),
        )
        sha = str(
            run_git(["rev-parse", "HEAD"], cwd=folder, timeout=_commit_timeout(respond_by))
        ).strip()
        branch = conflict_branch_name(sha, now=now)
        run_git(["branch", branch, sha], cwd=plan.worktree, timeout=_commit_timeout(respond_by))
        return branch, sha
    finally:
        _remove_worktree(plan, folder, respond_by)


def _commit_timeout(respond_by: Deadline) -> float:
    """置き換えの後の git の 1 回の呼び出しの制限時間を、呼ぶ直前の応答の上限までの残りで求める。"""
    return respond_by.remaining() - DIRECT_COMMIT_MARGIN_SEC


def _remove_worktree(plan: CommitPlan, folder: Path, respond_by: Deadline) -> None:
    """一時のワークツリーを削除する。git で削除できなければフォルダを削除して登録を掃除する。"""
    try:
        run_git(
            ["worktree", "remove", "--force", str(folder)],
            cwd=plan.worktree,
            timeout=_commit_timeout(respond_by),
        )
    except GitError as error:
        logger.warning("一時のワークツリーを削除できなかった（%s・%s）", folder, error)
        shutil.rmtree(folder, ignore_errors=True)
        run_git(["worktree", "prune"], cwd=plan.worktree, timeout=_commit_timeout(respond_by))


def run_conflict_script(
    script: OnConflictScript, *, cwd: Path, env: Mapping[str, str], timeout_sec: float
) -> ScriptRunResult:
    """端末の設定の衝突したときのスクリプトを実行し、終了コードと出力の末尾を返す。"""
    # 応答の上限までに時間が残っていない: 実行しない
    if timeout_sec <= 0:
        return ScriptRunResult(exit_code=None, timed_out=True, stdout="", stderr="")
    try:
        result = run_script(script.command, cwd=cwd, env=dict(env), timeout_sec=timeout_sec)
    except ScriptFailedError as error:
        # 終了コードが 0 以外: ブランチは残したまま、終了コードと出力を返す
        logger.warning(
            "衝突したときのスクリプトが失敗した（%s・終了コード %s）",
            script.command,
            error.exit_code,
        )
        return _tail(error.exit_code, timed_out=False, stdout=error.stdout, stderr=error.stderr)
    except ScriptTimeoutError:
        # 制限時間で止めた: 止めたときの出力は持たない
        return ScriptRunResult(exit_code=None, timed_out=True, stdout="", stderr="")
    except ScriptNotFoundError as error:
        # コマンドが見つからない: 理由を標準エラー出力に入れる
        return _tail(None, timed_out=False, stdout="", stderr=error.reason)
    return _tail(0, timed_out=False, stdout=result.stdout, stderr=result.stderr)


def _tail(exit_code: int | None, *, timed_out: bool, stdout: str, stderr: str) -> ScriptRunResult:
    """標準出力と標準エラー出力を末尾 `SCRIPT_OUTPUT_TAIL_CHARS` 文字にした結果を作る。"""
    return ScriptRunResult(
        exit_code=exit_code,
        timed_out=timed_out,
        stdout=stdout[-SCRIPT_OUTPUT_TAIL_CHARS:],
        stderr=stderr[-SCRIPT_OUTPUT_TAIL_CHARS:],
    )

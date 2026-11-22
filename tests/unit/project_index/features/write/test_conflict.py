from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from project_index.features.settings.types import OnConflictScript
from project_index.features.write import conflict
from project_index.features.write.conflict import (
    conflict_branch_name,
    keep_in_branch,
    run_conflict_script,
    verify_base_commit,
)
from project_index.features.write.direct_commit import CommitPlan
from project_index.shared.errors import BaseCommitUnusableError, ValidationFailedError, Violation

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class Remote:
    """テスト用のベアリポジトリと、develop のワークツリーを持つクローン。"""

    bare: Path
    clone: Path
    develop: Path


@pytest.fixture(autouse=True)
def git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """コミットの作成者と、端末の git の設定を読まないことを決める。"""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "tester")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "tester@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "tester")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "tester@example.com")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")


@pytest.fixture
def remote(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
) -> Remote:
    """ベアリポジトリ・クローン本体（master）・develop のワークツリーを作る。"""
    bare = tmp_path / "remote.git"
    run_git(tmp_path, "init", "--bare", "-b", "master", str(bare))
    clone = git_repo(
        {"docs/n1.yaml": "id: n1\nname: 1\n", "docs/n2.yaml": "id: n2\nname: 2\n"},
        name="clone",
        branch="master",
    )
    run_git(clone, "remote", "add", "origin", str(bare))
    run_git(clone, "branch", "develop")
    run_git(clone, "push", "origin", "master", "develop")
    develop = clone / ".claude" / "worktrees" / "develop"
    run_git(clone, "worktree", "add", str(develop), "develop")
    run_git(develop, "branch", "--set-upstream-to=origin/develop")
    return Remote(bare=bare, clone=clone, develop=develop)


@pytest.fixture
def plan(remote: Remote) -> CommitPlan:
    """develop へ直コミットする計画を返す。"""
    return CommitPlan(
        source_id="sample",
        branch="develop",
        worktree=remote.develop,
        repo=remote.clone / ".git",
        message="docs: n2 を更新する",
        base=remote.develop,
    )


def _push_change(remote: Remote, run_git: Callable[..., str], name: str, content: str) -> str:
    """develop のワークツリーで 1 コミットを作ってプッシュし、そのコミットの SHA を返す。"""
    (remote.develop / name).write_text(content, encoding="utf-8")
    run_git(remote.develop, "commit", "-am", f"{name} を変える")
    run_git(remote.develop, "push", "origin", "develop")
    return run_git(remote.develop, "rev-parse", "HEAD").strip()


def _write_n2(folder: Path) -> list[Path]:
    """配信元のフォルダの n2 を書き換え、書いたファイルを返す。"""
    target = folder / "docs" / "n2.yaml"
    target.write_text("id: n2\nname: 新しい 2\n", encoding="utf-8")
    return [target]


def test_verify_base_commit(
    remote: Remote, plan: CommitPlan, run_git: Callable[..., str]
) -> None:
    """短縮の SHA を 40 桁にする（正常系）。"""
    # 準備
    first = run_git(remote.develop, "rev-parse", "HEAD").strip()
    _push_change(remote, run_git, "docs/n1.yaml", "id: n1\nname: 新しい 1\n")
    # 実行
    result = verify_base_commit(first[:7], plan=plan, timeout=10)
    # 検証
    assert result == first


def test_verify_base_commit_when_not_found(plan: CommitPlan) -> None:
    """クローンに無いコミット（異常系）。"""
    # 準備
    missing = "0123456789abcdef0123456789abcdef01234567"
    # 実行・検証
    with pytest.raises(BaseCommitUnusableError, match=missing) as info:
        verify_base_commit(missing, plan=plan, timeout=10)
    assert info.value.reason == "not_found"


def test_verify_base_commit_when_not_ancestor(
    remote: Remote, plan: CommitPlan, run_git: Callable[..., str]
) -> None:
    """コミットするブランチの祖先でないコミット（異常系）。"""
    # 準備
    run_git(remote.clone, "checkout", "-b", "side")
    (remote.clone / "docs" / "n1.yaml").write_text("id: n1\nname: 別\n", encoding="utf-8")
    run_git(remote.clone, "commit", "-am", "別のブランチだけの変更")
    side = run_git(remote.clone, "rev-parse", "HEAD").strip()
    # 実行・検証
    with pytest.raises(BaseCommitUnusableError, match="develop") as info:
        verify_base_commit(side, plan=plan, timeout=10)
    assert info.value.reason == "not_ancestor"


def test_conflict_branch_name() -> None:
    """UTC の時刻とコミットの 7 桁（正常系）。"""
    # 準備
    now = datetime(2026, 11, 23, 9, 8, 7, tzinfo=timezone(timedelta(hours=9)))
    # 実行
    result = conflict_branch_name("0a1b2c3d4e5f60718293a4b5c6d7e8f901234567", now=now)
    # 検証
    assert result == "project-index/conflict/20261123-000807-0a1b2c3"


def test_keep_in_branch(
    tmp_path: Path, remote: Remote, plan: CommitPlan, run_git: Callable[..., str]
) -> None:
    """編集を始めたときのコミットからのブランチに 1 つのコミットを残す（正常系）。"""
    # 準備
    base_sha = run_git(remote.develop, "rev-parse", "HEAD").strip()
    _push_change(remote, run_git, "docs/n1.yaml", "id: n1\nname: 新しい 1\n")
    state_dir = tmp_path / "state"
    now = datetime(2026, 11, 23, 0, 8, 7, tzinfo=UTC)
    # 実行
    result = keep_in_branch(
        plan,
        base_sha=base_sha,
        write_once=_write_n2,
        state_dir=state_dir,
        commit=True,
        now=now,
        timeout=10,
        commit_timeout=10,
    )
    # 検証
    assert result is not None
    branch, commit = result
    assert branch == f"project-index/conflict/20261123-000807-{commit[:7]}"
    assert run_git(remote.clone, "rev-parse", f"{branch}~1").strip() == base_sha
    assert run_git(remote.clone, "rev-parse", branch).strip() == commit
    changed = run_git(remote.clone, "diff", "--name-only", f"{branch}~1", branch).split()
    assert changed == ["docs/n2.yaml"]
    assert run_git(remote.clone, "log", "-1", "--format=%s", branch).strip() == plan.message
    assert run_git(remote.bare, "branch", "--list", branch).strip() == ""
    assert list((state_dir / "conflicts").iterdir()) == []
    assert run_git(remote.clone, "worktree", "list").count("\n") == 2


def test_keep_in_branch_when_write_fails(
    tmp_path: Path, remote: Remote, plan: CommitPlan, run_git: Callable[..., str]
) -> None:
    """書き込みの失敗をそのまま送り、一時のワークツリーを残さない（異常系）。"""
    # 準備
    base_sha = run_git(remote.develop, "rev-parse", "HEAD").strip()
    state_dir = tmp_path / "state"
    branches_before = run_git(remote.clone, "branch", "--list", "project-index/*")

    def fail(_folder: Path) -> list[Path]:
        raise ValidationFailedError(
            [Violation(path="writes[0]", rule="スキーマに違反する", fix="値を直す")]
        )

    # 実行・検証
    with pytest.raises(ValidationFailedError):
        keep_in_branch(
            plan,
            base_sha=base_sha,
            write_once=fail,
            state_dir=state_dir,
            commit=True,
            now=datetime(2026, 11, 23, tzinfo=UTC),
            timeout=10,
            commit_timeout=10,
        )
    assert run_git(remote.clone, "branch", "--list", "project-index/*") == branches_before
    assert list((state_dir / "conflicts").iterdir()) == []
    assert run_git(remote.clone, "worktree", "list").count("\n") == 2


def test_keep_in_branch_when_dry_run(
    tmp_path: Path, remote: Remote, plan: CommitPlan, run_git: Callable[..., str]
) -> None:
    """試しに書くとコミットしない（正常系）。"""
    # 準備
    base_sha = run_git(remote.develop, "rev-parse", "HEAD").strip()
    calls: list[Path] = []

    def record(folder: Path) -> list[Path]:
        calls.append(folder)
        return _write_n2(folder)

    commits_before = run_git(remote.clone, "rev-list", "--all", "--count").strip()
    # 実行
    result = keep_in_branch(
        plan,
        base_sha=base_sha,
        write_once=record,
        state_dir=tmp_path / "state",
        commit=False,
        now=datetime(2026, 11, 23, tzinfo=UTC),
        timeout=10,
        commit_timeout=10,
    )
    # 検証
    assert result is None
    assert len(calls) == 1
    assert run_git(remote.clone, "branch", "--list", "project-index/*").strip() == ""
    assert run_git(remote.clone, "rev-list", "--all", "--count").strip() == commits_before


def test_keep_in_branch_when_write_deadline_passed(
    tmp_path: Path, remote: Remote, plan: CommitPlan, run_git: Callable[..., str]
) -> None:
    """書き込みの期限の直前に検査が終わってもブランチを残す（正常系）。"""
    # 準備
    base_sha = run_git(remote.develop, "rev-parse", "HEAD").strip()

    def slow(folder: Path) -> list[Path]:
        time.sleep(1)
        return _write_n2(folder)

    # 実行
    result = keep_in_branch(
        plan,
        base_sha=base_sha,
        write_once=slow,
        state_dir=tmp_path / "state",
        commit=True,
        now=datetime(2026, 11, 23, tzinfo=UTC),
        timeout=1,
        commit_timeout=10,
    )
    # 検証
    assert result is not None
    branch, _commit = result
    changed = run_git(remote.clone, "diff", "--name-only", f"{branch}~1", branch).split()
    assert changed == ["docs/n2.yaml"]


ENV = {
    "PROJECT_INDEX_SOURCE": "sample",
    "PROJECT_INDEX_CONFLICT_BRANCH": "project-index/conflict/20261123-000807-0a1b2c3",
    "PROJECT_INDEX_CONFLICT_COMMIT": "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567",
    "PROJECT_INDEX_BASE_COMMIT": "1b2c3d4e5f60718293a4b5c6d7e8f9012345678a",
    "PROJECT_INDEX_TARGET_BRANCH": "develop",
    "PROJECT_INDEX_COMMIT_MESSAGE": "docs: n2 を更新する",
}


def test_run_conflict_script(tmp_path: Path) -> None:
    """環境変数を受けて出力を返す（正常系）。"""
    # 準備
    script = OnConflictScript(
        command=[
            sys.executable,
            "-c",
            "import os; print(os.environ['PROJECT_INDEX_CONFLICT_BRANCH'], end='')",
        ]
    )
    # 実行
    result = run_conflict_script(script, cwd=tmp_path, env=ENV, timeout_sec=10)
    # 検証
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.stdout == "project-index/conflict/20261123-000807-0a1b2c3"


def test_run_conflict_script_when_failed(tmp_path: Path) -> None:
    """失敗しても終了コードと出力を返す（正常系）。"""
    # 準備
    script = OnConflictScript(
        command=[
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('a' * 1000 + 'b' * 8000); sys.exit(3)",
        ]
    )
    # 実行
    result = run_conflict_script(script, cwd=tmp_path, env=ENV, timeout_sec=10)
    # 検証
    assert result.exit_code == 3
    assert result.timed_out is False
    assert result.stderr == "b" * 8000


def test_run_conflict_script_when_timeout(tmp_path: Path) -> None:
    """制限時間で止める（正常系）。"""
    # 準備
    script = OnConflictScript(command=[sys.executable, "-c", "import time; time.sleep(5)"])
    # 実行
    result = run_conflict_script(script, cwd=tmp_path, env=ENV, timeout_sec=0.5)
    # 検証
    assert result.exit_code is None
    assert result.timed_out is True


def test_run_conflict_script_when_no_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """残りの時間が無ければ実行しない（正常系）。"""
    # 準備
    calls: list[object] = []
    monkeypatch.setattr(conflict, "run_script", lambda *args, **kwargs: calls.append(args))
    script = OnConflictScript(command=[sys.executable, "-c", "print('x')"])
    # 実行
    result = run_conflict_script(script, cwd=tmp_path, env=ENV, timeout_sec=0)
    # 検証
    assert result.exit_code is None
    assert result.timed_out is True
    assert calls == []


def test_run_conflict_script_when_not_found(tmp_path: Path) -> None:
    """コマンドが見つからない（正常系）。"""
    # 準備
    script = OnConflictScript(command=["project-index-no-such-command"])
    # 実行
    result = run_conflict_script(script, cwd=tmp_path, env=ENV, timeout_sec=10)
    # 検証
    assert result.exit_code is None
    assert result.timed_out is False
    assert "project-index-no-such-command" in result.stderr


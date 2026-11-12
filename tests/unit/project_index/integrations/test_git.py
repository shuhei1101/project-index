from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

import pytest

from project_index.integrations import git as git_module
from project_index.integrations.git import GitError, is_ignored, repo_root, run_git

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_run_git(git_repo: Callable[..., Path]) -> None:
    """標準出力を返す（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    # 実行
    result = run_git(["rev-parse", "--is-inside-work-tree"], cwd=root)
    # 検証
    assert result == "true\n"


def test_run_git_when_failed(git_repo: Callable[..., Path]) -> None:
    """失敗を例外にする（異常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    # 実行・検証
    with pytest.raises(GitError) as exc_info:
        run_git(["rev-parse", "nope"], cwd=root)
    assert exc_info.value.returncode != 0
    assert "nope" in exc_info.value.stderr


def test_run_git_when_timeout(
    git_repo: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """待ち時間の上限を超える（異常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    monkeypatch.setattr(git_module, "GIT_TIMEOUT_SEC", 0.1)
    monkeypatch.setenv("GIT_EDITOR", "sleep 1; true")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "tester")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "tester@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "tester")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "tester@example.com")
    started: list[subprocess.Popen[Any]] = []
    real_popen = subprocess.Popen

    def recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
        """起こした子プロセスを控えて返す。"""
        process = real_popen(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", recording_popen)
    # 実行・検証
    with pytest.raises(GitError) as exc_info:
        run_git(["commit", "--allow-empty"], cwd=root)
    assert exc_info.value.timed_out is True
    assert started
    assert all(process.poll() is not None for process in started)


def test_run_git_when_timeout_given(
    git_repo: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """指定した待ち時間の上限を超える（異常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    monkeypatch.setenv("GIT_EDITOR", "sleep 1; true")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "tester")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "tester@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "tester")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "tester@example.com")
    # 実行・検証
    with pytest.raises(GitError, match=r"0\.1 秒を超えたため止めました") as exc_info:
        run_git(["commit", "--allow-empty"], cwd=root, timeout=0.1)
    assert exc_info.value.timed_out is True


def test_repo_root(git_repo: Callable[..., Path]) -> None:
    """リポジトリの中のフォルダ（正常系）。"""
    # 準備
    root = git_repo({"docs/a.yaml": "a: 1\n"})
    # 実行
    result = repo_root(root / "docs")
    # 検証
    assert result == root


def test_repo_root_when_not_git(tmp_path: Path) -> None:
    """Git の管理外（正常系）。"""
    # 実行
    result = repo_root(tmp_path)
    # 検証
    assert result is None


def test_main_repo_root(git_repo: Callable[..., Path], run_git: Callable[..., str]) -> None:
    """クローン本体とワークツリー（正常系）。"""
    from project_index.integrations.git import main_repo_root

    # 準備
    root = git_repo({"docs/a.yaml": "a: 1\n"})
    worktree = root / ".claude" / "worktrees" / "x"
    run_git(root, "worktree", "add", "-b", "feat/x", str(worktree))
    # 実行
    results = [main_repo_root(root), main_repo_root(worktree / "docs")]
    # 検証
    assert results == [root.resolve(), root.resolve()]


def test_main_repo_root_when_not_git(tmp_path: Path) -> None:
    """Git の管理外（正常系）。"""
    from project_index.integrations.git import main_repo_root

    # 実行
    result = main_repo_root(tmp_path)
    # 検証
    assert result is None


def test_is_ignored(git_repo: Callable[..., Path]) -> None:
    """無視されている（正常系）。"""
    # 準備
    root = git_repo({".gitignore": "project-index.local.yaml\n"})
    (root / "project-index.local.yaml").write_text("name: x\n", encoding="utf-8")
    # 実行
    result = is_ignored(root / "project-index.local.yaml", root)
    # 検証
    assert result is True


def test_is_ignored_when_not_ignored(git_repo: Callable[..., Path]) -> None:
    """無視されていない（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    (root / "project-index.yaml").write_text("name: x\n", encoding="utf-8")
    # 実行
    result = is_ignored(root / "project-index.yaml", root)
    # 検証
    assert result is False

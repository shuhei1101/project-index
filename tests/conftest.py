from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

GIT_ENV = {
    "GIT_AUTHOR_NAME": "tester",
    "GIT_AUTHOR_EMAIL": "tester@example.com",
    "GIT_COMMITTER_NAME": "tester",
    "GIT_COMMITTER_EMAIL": "tester@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


@pytest.fixture
def run_git() -> Callable[..., str]:
    """git を実行して標準出力を返す関数を返す。"""

    def _run(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, **GIT_ENV, **(env or {})},
        )
        return result.stdout

    return _run


@pytest.fixture
def write_files() -> Callable[[Path, dict[str, str]], None]:
    """フォルダの下に、パス → 内容のファイルを書く関数を返す。"""

    def _write(root: Path, files: dict[str, str]) -> None:
        for name, content in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    return _write


@pytest.fixture
def git_repo(
    tmp_path: Path,
    run_git: Callable[..., str],
    write_files: Callable[[Path, dict[str, str]], None],
) -> Callable[..., Path]:
    """ファイルを commit した git リポジトリを作る関数を返す。"""

    def _create(
        files: dict[str, str],
        name: str = "repo",
        branch: str = "develop",
        date: str | None = None,
    ) -> Path:
        root = tmp_path / name
        root.mkdir(parents=True)
        run_git(root, "init", "-b", branch)
        write_files(root, files)
        run_git(root, "add", "-A")
        run_git(root, "commit", "-m", "init", env=_date_env(date))
        return root

    return _create


def _date_env(date: str | None) -> dict[str, str]:
    """commit の日時を固定する環境変数を返す。"""
    if date is None:
        return {}
    return {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}


@pytest.fixture
def commit_all(
    run_git: Callable[..., str],
    write_files: Callable[[Path, dict[str, str]], None],
) -> Callable[..., str]:
    """ファイルを書き換えて commit し、commit の SHA を返す関数を返す。"""

    def _commit(
        repo: Path,
        files: dict[str, str],
        message: str = "update",
        *,
        date: str | None = None,
        delete: tuple[str, ...] = (),
    ) -> str:
        write_files(repo, files)
        for name in delete:
            (repo / name).unlink()
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-m", message, env=_date_env(date))
        return run_git(repo, "rev-parse", "HEAD").strip()

    return _commit

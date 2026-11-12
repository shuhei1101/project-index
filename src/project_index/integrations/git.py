"""git の子プロセスでの実行。"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from project_index.shared.paths import normalize_path

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

GIT_TIMEOUT_SEC = 8
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"}
GIT_ARCHIVE_TIMEOUT_SEC = 20
STDERR_TAIL_LINES = 5


class GitError(Exception):
    """git が 0 以外で終わったか待ち時間の上限を超えたこと。"""

    def __init__(
        self, args_: list[str], returncode: int, stderr: str, *, timed_out: bool = False
    ) -> None:
        super().__init__(f"git {' '.join(args_)}: {stderr}")
        self.args_ = args_
        self.returncode = returncode
        self.stderr = stderr
        self.timed_out = timed_out


def _tail(text: str) -> str:
    """標準エラーの末尾 `STDERR_TAIL_LINES` 行を返す。"""
    return "\n".join(text.strip().splitlines()[-STDERR_TAIL_LINES:])


def run_git(
    args: Sequence[str], *, cwd: Path, binary: bool = False, timeout: float | None = None
) -> str | bytes:
    """git を子プロセスで 1 回呼び、標準出力を返す。"""
    # 待ち時間の上限は、指定が無ければ git の呼び出しに共通の上限にする
    limit = GIT_TIMEOUT_SEC if timeout is None else timeout
    command = ["git", *args]
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
            env={**os.environ, **GIT_ENV},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=limit,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        # 待ち時間の上限を超えたときは run が子プロセスを止めてからここへ来る
        logger.warning(
            "git が待ち時間の上限を超えた（引数: %s・cwd: %s・%s 秒）",
            list(args),
            cwd,
            limit,
        )
        raise GitError(
            list(args),
            -1,
            f"{limit} 秒を超えたため止めました",
            timed_out=True,
        ) from error
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")
        raise GitError(list(args), completed.returncode, _tail(stderr))
    if binary:
        return completed.stdout
    return completed.stdout.decode("utf-8")


def repo_root(path: Path) -> Path | None:
    """フォルダが Git の作業ツリーの中なら、その直下を返す。"""
    try:
        output = run_git(["rev-parse", "--show-toplevel"], cwd=path)
    except GitError, FileNotFoundError, NotADirectoryError:
        return None
    text = output if isinstance(output, str) else output.decode("utf-8")
    return normalize_path(text.rstrip("\n"))


def main_repo_root(path: Path) -> Path | None:
    """ワークツリーの中からでも、メインのリポジトリ（クローン本体）の直下を返す。"""
    try:
        output = run_git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=path)
    except GitError, FileNotFoundError, NotADirectoryError:
        return None
    text = output if isinstance(output, str) else output.decode("utf-8")
    return normalize_path(str(Path(text.rstrip("\n")).parent))


def is_ignored(path: Path, top: Path) -> bool:
    """ファイルが `.gitignore` などで無視されているかを返す。"""
    try:
        relative = Path(os.path.abspath(path)).relative_to(top).as_posix()
        run_git(["check-ignore", "-q", "--", relative], cwd=top)
    except GitError, ValueError, FileNotFoundError, NotADirectoryError:
        # 無視されていない（終了コード 1）と、失敗（128）は区別しない
        return False
    return True

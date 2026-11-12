"""配信元のスクリプトの制限時間つきの実行。"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence

logger = logging.getLogger(__name__)

STDERR_TAIL_LINES = 5
KILL_GRACE_SEC = 2
SCRIPT_SUFFIXES = (".py", ".sh", ".js", ".ts")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScriptResult:
    """終了コード 0 で終えたスクリプトの標準出力と標準エラー。"""

    stdout: str
    stderr: str


class ScriptError(Exception):
    """スクリプトを動かせない・失敗したことを表す基底。"""

    def __init__(
        self, run: list[str], reason: str, *, exit_code: int | None = None, stdout: str = ""
    ) -> None:
        super().__init__(reason)
        self.run = run
        self.reason = reason
        self.exit_code = exit_code
        self.stdout = stdout


class ScriptNotFoundError(ScriptError):
    """コマンドが見つからない。"""


class ScriptTimeoutError(ScriptError):
    """制限時間を超えた。"""


class ScriptFailedError(ScriptError):
    """終了コードが 0 以外。"""


def check_runnable(run: Sequence[str], *, cwd: Path) -> list[str]:
    """コマンドの先頭と、配信元の中のスクリプトのファイルがあるかを確かめる。"""
    command = list(run)
    if not command:
        raise ScriptNotFoundError(command, "コマンドが空です")
    head = command[0]
    # `/` を含む先頭は cwd からのパス、含まないときは PATH から引く
    resolved = str((cwd / head).resolve()) if "/" in head and (cwd / head).exists() else None
    if resolved is None and "/" not in head:
        # PATH に無ければ、サーバーを動かしている Python の環境の bin から引く（子プロセスの PATH は変えない）
        resolved = shutil.which(head) or shutil.which(head, path=str(Path(sys.executable).parent))
    if resolved is None:
        raise ScriptNotFoundError(command, f"コマンド {head} が見つかりません")
    # cwd からの相対パスに見えるスクリプトの引数は、ファイルがあること
    for argument in command[1:]:
        if (
            PurePosixPath(argument).suffix in SCRIPT_SUFFIXES
            and not argument.startswith(("-", "/"))
            and not (cwd / argument).exists()
        ):
            raise ScriptNotFoundError(command, f"スクリプト {argument} が見つかりません")
    return [resolved, *command[1:]]


def _stop(process: subprocess.Popen[bytes]) -> None:
    """プロセスグループに SIGTERM を送り、猶予の後に残っていれば SIGKILL を送る。"""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=KILL_GRACE_SEC)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait()


@contextmanager
def _run_at(run: Sequence[str], cwd: Path, at: tuple[Path, str] | None) -> Generator[list[str]]:
    """`run` のうち commit にあるファイルを、そのリビジョンから取り出したファイルに置き換える。"""
    command = list(run)
    if at is None:
        yield command
        return
    from project_index.features.history.query import export_paths_at, read_file_at

    repo, commit = at
    prefix = (
        cwd.resolve().relative_to(repo.resolve())
        if cwd.resolve().is_relative_to(repo.resolve())
        else None
    )
    with ExitStack() as stack:
        for position, item in enumerate(command):
            if prefix is None or item.startswith("-") or Path(item).is_absolute():
                continue
            relative = (prefix / item).as_posix()
            if read_file_at(repo, commit, relative) is None:
                continue
            exported = stack.enter_context(
                export_paths_at(repo, commit, [PurePosixPath(relative).parent.as_posix()])
            )
            command[position] = str(exported / relative)
        yield command


def run_script(
    run: Sequence[str],
    *,
    cwd: Path,
    stdin: str = "",
    args: Sequence[str] = (),
    timeout_sec: float,
    at: tuple[Path, str] | None = None,
) -> ScriptResult:
    """コマンドを配信元の直下で動かし、制限時間を超えたら止める。"""
    with _run_at(run, cwd, at) as resolved:
        return _run(resolved, list(run), cwd=cwd, stdin=stdin, args=args, timeout_sec=timeout_sec)


def _run(
    resolved: list[str],
    run: list[str],
    *,
    cwd: Path,
    stdin: str,
    args: Sequence[str],
    timeout_sec: float,
) -> ScriptResult:
    """置き換えたコマンドを動かす。"""
    command = check_runnable(resolved, cwd=cwd)
    full = [*command, *args]
    process = subprocess.Popen(  # noqa: S603
        full,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(stdin.encode("utf-8"), timeout=timeout_sec)
    except subprocess.TimeoutExpired as error:
        _stop(process)
        process.communicate()
        logger.warning(
            "スクリプトを制限時間で止めた（コマンド: %s・cwd: %s・%s 秒）",
            list(run),
            cwd,
            timeout_sec,
        )
        raise ScriptTimeoutError(
            list(run), f"制限時間（{timeout_sec} 秒）を超えたため、スクリプトを止めました。"
        ) from error
    out_text = stdout.decode("utf-8", errors="replace")
    err_text = stderr.decode("utf-8", errors="replace")
    if process.returncode != 0:
        tail = "\n".join(err_text.strip().splitlines()[-STDERR_TAIL_LINES:])
        raise ScriptFailedError(
            list(run),
            f"終了コード {process.returncode} で終わりました。\n{tail}",
            exit_code=process.returncode,
            stdout=out_text,
        )
    return ScriptResult(stdout=out_text, stderr=err_text)

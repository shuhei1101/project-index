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

from project_index.integrations.git import GitError, run_git
from project_index.shared.hashing import value_hash

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence

logger = logging.getLogger(__name__)

STDERR_TAIL_LINES = 5
KILL_GRACE_SEC = 2
SCRIPT_SUFFIXES = (".py", ".sh", ".js", ".ts")
# スクリプトの実行で書かれ、スクリプトの状態に含めないフォルダ
_SCRIPT_CACHE_DIR = "__pycache__"
# 状態を取れなかったファイルの更新時刻と大きさ
_UNKNOWN_STAT = -1


@dataclass(frozen=True, slots=True, kw_only=True)
class ScriptResult:
    """終了コード 0 で終えたスクリプトの標準出力と標準エラー。"""

    stdout: str
    stderr: str


class ScriptError(Exception):
    """スクリプトを動かせない・失敗したことを表す基底。"""

    def __init__(
        self,
        run: list[str],
        reason: str,
        *,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(reason)
        self.run = run
        self.reason = reason
        self.exit_code = exit_code
        self.stdout = stdout
        # `ScriptFailedError` だけが持つ。標準エラー出力の全て
        self.stderr = stderr


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
    env: Mapping[str, str | None] | None = None,
) -> ScriptResult:
    """コマンドを配信元の直下で動かし、制限時間を超えたら止める。"""
    with _run_at(run, cwd, at) as resolved:
        return _run(
            resolved,
            list(run),
            cwd=cwd,
            stdin=stdin,
            args=args,
            timeout_sec=timeout_sec,
            env=_child_env(env),
        )


def _child_env(env: Mapping[str, str | None] | None) -> dict[str, str] | None:
    """サーバーの環境変数に `env` を重ねた子プロセスの環境を返す（値が `None` のキーは除く）。"""
    # 重ねる値が無い: サーバーの環境をそのまま引き継ぐ
    if env is None:
        return None
    merged = dict(os.environ)
    for key, value in env.items():
        # 値が None のキーは子プロセスに渡さない
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _run(
    resolved: list[str],
    run: list[str],
    *,
    cwd: Path,
    stdin: str,
    args: Sequence[str],
    timeout_sec: float,
    env: dict[str, str] | None,
) -> ScriptResult:
    """置き換えたコマンドを動かす。"""
    command = check_runnable(resolved, cwd=cwd)
    full = [*command, *args]
    process = subprocess.Popen(  # noqa: S603
        full,
        cwd=cwd,
        env=env,
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
            stderr=err_text,
        )
    return ScriptResult(stdout=out_text, stderr=err_text)


def script_stamp(base: Path, run: Sequence[str], *, use_git: bool) -> str:
    """`run` が指すファイルのフォルダの配下（`__pycache__` を除く）の `stat` のハッシュを返す。"""
    folders = _script_folders(base, run)
    # 作業ツリーにスクリプトのファイルが無い（コマンドだけの `run`）
    if not folders:
        return ""
    stamps: list[tuple[str, int, int]] = []
    for folder in sorted(folders):
        stamps.extend(_folder_stamps(base, folder, use_git=use_git))
    return value_hash(stamps)


def _script_folders(base: Path, run: Sequence[str]) -> set[Path]:
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
    if use_git:
        try:
            files = _git_files(folder)
        except GitError as error:
            # リポジトリの外のフォルダ・git の待ち時間の超過: たどって状態を作り、検索を止めない
            logger.warning("スクリプトのフォルダを git で列挙できない（%s）: %s", folder, error)
            files = _walked_files(folder)
    else:
        files = _walked_files(folder)
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

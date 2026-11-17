"""commit のファイルの blob の内容の、書き出さない読み取り。"""

from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import weakref
from typing import TYPE_CHECKING

from project_index.integrations.git import GIT_ENV, GitError

if TYPE_CHECKING:
    from pathlib import Path

# 標準入力を閉じた `git cat-file --batch` の終わりを待つ秒数（標準入力を閉じると次の行を読まずに終わる）
BLOB_READER_STOP_SEC = 5

__all__ = ["BLOB_READER_STOP_SEC", "BlobReader"]

_COMMAND = ["git", "cat-file", "--batch"]


class _ProcessExitedError(Exception):
    """1 往復の途中で `git cat-file --batch` が終わったこと。"""


class BlobReader:
    """1 つのリポジトリの `git cat-file --batch` を 1 本だけ動かし続け、blob の SHA から内容を返す。"""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        # 初めての読み取りで起動する
        self._process: subprocess.Popen[bytes] | None = None
        # 1 往復の書き込みと読み取りを 1 つのスレッドだけが行う
        self._lock = threading.Lock()

    def read_bytes(self, blob: str) -> bytes | None:
        """blob の内容をバイト列で返す（リポジトリに無い SHA は `None`）。"""
        with self._lock:
            try:
                return self._exchange(blob)
            except _ProcessExitedError:
                # 子プロセスが終わっていた: 起動し直して 1 回だけやり直す
                self._stop()
            try:
                return self._exchange(blob)
            except _ProcessExitedError as error:
                self._stop()
                raise GitError(_COMMAND[1:], -1, "git cat-file --batch が終了しました") from error

    def read_text(self, blob: str) -> str | None:
        """blob の内容を UTF-8 の文字列で返す（無い SHA と UTF-8 で読めない内容は `None`）。"""
        data = self.read_bytes(blob)
        if data is None:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def close(self) -> None:
        """子プロセスを止める。"""
        with self._lock:
            self._stop()

    def _exchange(self, blob: str) -> bytes | None:
        """子プロセスへ SHA を 1 行送り、見出しと内容を読む（`_lock` の中で呼ぶ）。"""
        process = self._running()
        stdin, stdout = process.stdin, process.stdout
        if stdin is None or stdout is None:
            raise _ProcessExitedError
        try:
            stdin.write(f"{blob}\n".encode())
            stdin.flush()
            header = stdout.readline()
        except (BrokenPipeError, OSError) as error:
            raise _ProcessExitedError from error
        # 見出しが空: 子プロセスが終わっている
        if not header:
            raise _ProcessExitedError
        fields = header.decode().split()
        # `{SHA} missing`: リポジトリに無い SHA
        if len(fields) < 3 or fields[1] == "missing":  # noqa: PLR2004
            return None
        size = int(fields[2])
        data = stdout.read(size)
        # 内容の後の改行を読み捨てる
        stdout.read(1)
        if len(data) != size:
            raise _ProcessExitedError
        return data

    def _running(self) -> subprocess.Popen[bytes]:
        """動いている子プロセスを返す（無いか終わっていれば起動する）。"""
        if self._process is None or self._process.poll() is not None:
            self._stop()
            self._process = subprocess.Popen(  # noqa: S603
                _COMMAND,
                cwd=self.repo_root,
                env={**os.environ, **GIT_ENV},
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            # 読み取りが捨てられたときも子プロセスを止める
            weakref.finalize(self, _terminate, self._process)
        return self._process

    def _stop(self) -> None:
        """子プロセスがあれば止めて `None` にする（`_lock` の中で呼ぶ）。"""
        process = self._process
        self._process = None
        if process is not None:
            _terminate(process)


def _terminate(process: subprocess.Popen[bytes]) -> None:
    """子プロセスの標準入力を閉じて終わりを待ち（上限を超えたら kill）、標準出力を閉じる。"""
    # 既に終わった子プロセスのパイプは閉じられない
    with contextlib.suppress(OSError):
        if process.stdin is not None:
            process.stdin.close()
    try:
        process.wait(timeout=BLOB_READER_STOP_SEC)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    if process.stdout is not None:
        process.stdout.close()

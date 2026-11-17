"""リビジョンの書き出し。"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import shutil
import tarfile
import threading
import time
from typing import TYPE_CHECKING

from project_index import poc_timing
from project_index.integrations.git import GIT_ARCHIVE_TIMEOUT_SEC, GitError, run_git
from project_index.shared.errors import RevisionExportTimeoutError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

logger = logging.getLogger(__name__)

SNAPSHOT_KEEP = 20

__all__ = ["SNAPSHOT_KEEP", "SnapshotStore", "run_git"]


class SnapshotStore:
    """commit のファイルを `state_dir` の下に書き出し、同じ commit は書き出したフォルダを返す。"""

    def __init__(self, dir: Path, keep: int = SNAPSHOT_KEEP) -> None:
        self.dir = dir
        self.keep = keep
        self._locks: dict[Path, threading.Lock] = {}
        self._guard = threading.Lock()
        # 裏の書き出しの開始が起こして終えていないスレッドの数
        self._background = 0

    @property
    def exporting(self) -> bool:
        """裏の書き出しが終わっていないかを返す。"""
        with self._guard:
            return self._background > 0

    def checkout_later(
        self, targets: list[tuple[Path, str]], *, after: Sequence[threading.Thread] = ()
    ) -> threading.Thread:
        """渡したスレッドの終了を待ってから、渡した commit を裏のスレッドで順に書き出す。"""
        with self._guard:
            self._background += 1

        def work() -> None:
            try:
                # PoC: 裏の書き出しを止める
                if poc_timing.flag("POC_NO_EXPORT"):
                    poc_timing.emit("export_skipped")
                    return
                after_sec = poc_timing.number("POC_EXPORT_AFTER")
                if after_sec is not None:
                    at = (poc_timing.number("POC_T0") or time.time()) + after_sec
                    # PoC: 検査を待たず、指定の時刻まで待ってから書き出す
                    time.sleep(max(0.0, at - time.time()))
                else:
                    # 検査を終えてから書き出す
                    for thread in after:
                        thread.join()
                poc_timing.emit("export_begin", count=len(targets))
                for repo_root, commit in targets:
                    try:
                        self.checkout(repo_root, commit)
                    except (RevisionExportTimeoutError, GitError) as error:
                        # 止めた commit は次の要求が書き出し直すので、ログに残して次へ進む
                        logger.warning(
                            "裏のリビジョンの書き出しを止めた（%s・%s・%s）",
                            repo_root,
                            commit,
                            error,
                        )
            finally:
                poc_timing.emit("export_end")
                with self._guard:
                    self._background -= 1

        thread = threading.Thread(target=work, name="project-index-revision-export", daemon=True)
        thread.start()
        return thread

    def _lock_for(self, target: Path) -> threading.Lock:
        """commit ごとの排他を引く（無ければ作る）。"""
        with self._guard:
            return self._locks.setdefault(target, threading.Lock())

    def checkout(self, repo_root: Path, commit: str) -> Path:
        """commit のファイルを書き出したフォルダを返す。"""
        repo_dir = self.dir / hashlib.sha256(str(repo_root).encode("utf-8")).hexdigest()[:12]
        target = repo_dir / commit
        if target.is_dir():
            os.utime(target)
            return target
        lock = self._lock_for(target)
        with poc_timing.span("checkout_lock_wait", repo=str(repo_root), commit=commit):
            lock.acquire()
        try:
            # 排他を待つ間に、他のスレッドが書き出したかもしれない
            if target.is_dir():
                os.utime(target)
                poc_timing.emit("checkout_done_by_other", repo=str(repo_root), commit=commit)
                return target
            temp = repo_dir / f"{commit}.tmp"
            shutil.rmtree(temp, ignore_errors=True)
            temp.mkdir(parents=True)
            try:
                with poc_timing.span("checkout_archive", repo=str(repo_root), commit=commit):
                    data = run_git(
                        ["archive", "--format=tar", commit],
                        cwd=repo_root,
                        binary=True,
                        timeout=GIT_ARCHIVE_TIMEOUT_SEC,
                    )
                if not isinstance(data, bytes):
                    msg = "git archive の出力がバイト列ではありません"
                    raise RuntimeError(msg)
                with (
                    poc_timing.span("checkout_extract", repo=str(repo_root), commit=commit),
                    tarfile.open(fileobj=io.BytesIO(data)) as archive,
                ):
                    archive.extractall(temp, filter="data")
            except GitError as error:
                shutil.rmtree(temp, ignore_errors=True)
                # 待ち時間の上限を超えたときは、止めた処理と理由を持つエラーにして送る
                if error.timed_out:
                    raise RevisionExportTimeoutError(
                        message=(
                            f"リビジョンの書き出し（{commit}）が "
                            f"{GIT_ARCHIVE_TIMEOUT_SEC:g} 秒を超えたため止めました"
                        ),
                        next_steps=["時間を空けて同じ呼び出しを再実行してください"],
                        commit=commit,
                        limit_sec=GIT_ARCHIVE_TIMEOUT_SEC,
                    ) from error
                raise
            temp.rename(target)
            os.utime(target)
            logger.info(
                "リビジョンを書き出した（%s・%s・%s ファイル）",
                repo_root,
                commit,
                sum(1 for item in target.rglob("*") if item.is_file()),
            )
            self._prune(repo_dir, target)
        finally:
            lock.release()
        return target

    def _prune(self, repo_dir: Path, current: Path) -> None:
        """書き出しが `keep` を超えたら、使った時刻が古いものから削除する（今のものは残す）。"""
        folders = [item for item in repo_dir.iterdir() if item.is_dir() and item.suffix != ".tmp"]
        excess = len(folders) - self.keep
        if excess <= 0:
            return
        old = sorted((item for item in folders if item != current), key=lambda i: i.stat().st_mtime)
        for item in old[:excess]:
            shutil.rmtree(item, ignore_errors=True)

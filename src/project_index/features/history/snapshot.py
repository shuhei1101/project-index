"""リビジョンの書き出し。"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import shutil
import tarfile
import threading
from typing import TYPE_CHECKING

from project_index.integrations.git import GitError, run_git

if TYPE_CHECKING:
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
        with self._lock_for(target):
            # 排他を待つ間に、他のスレッドが書き出したかもしれない
            if target.is_dir():
                os.utime(target)
                return target
            temp = repo_dir / f"{commit}.tmp"
            shutil.rmtree(temp, ignore_errors=True)
            temp.mkdir(parents=True)
            try:
                data = run_git(["archive", "--format=tar", commit], cwd=repo_root, binary=True)
                assert isinstance(data, bytes)  # noqa: S101
                with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                    archive.extractall(temp, filter="data")
            except GitError:
                shutil.rmtree(temp, ignore_errors=True)
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

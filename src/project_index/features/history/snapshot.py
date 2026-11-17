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

from project_index.integrations.git import GIT_ARCHIVE_TIMEOUT_SEC, GitError, run_git
from project_index.shared.background import BackgroundGate
from project_index.shared.errors import RevisionExportTimeoutError

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

SNAPSHOT_KEEP = 20

__all__ = ["SNAPSHOT_KEEP", "SnapshotStore", "run_git"]


class SnapshotStore:
    """commit のファイルを `state_dir` の下に書き出し、同じ commit は書き出したフォルダを返す。"""

    def __init__(
        self, dir: Path, keep: int = SNAPSHOT_KEEP, *, gate: BackgroundGate | None = None
    ) -> None:
        self.dir = dir
        self.keep = keep
        # 裏の書き出しを、要求の応答中は commit 1 件ごとに休ませる関所
        self.gate = gate if gate is not None else BackgroundGate()
        self._locks: dict[Path, threading.Lock] = {}
        self._guard = threading.Lock()
        # 裏の書き出しの開始が起こして終えていないスレッドの数
        self._background = 0

    @property
    def exporting(self) -> bool:
        """裏の書き出しが終わっていないかを返す。"""
        with self._guard:
            return self._background > 0

    def checkout_later(self, targets: list[tuple[Path, str]]) -> threading.Thread:
        """渡した commit を裏のスレッドで順に書き出し、待たずに戻る。"""
        with self._guard:
            self._background += 1

        def work() -> None:
            try:
                # commit 1 件ごとに、要求の応答中は関所で休みを挟む
                with self.gate.background():
                    for repo_root, commit in targets:
                        self._checkout_unit(repo_root, commit)
            finally:
                with self._guard:
                    self._background -= 1

        thread = threading.Thread(target=work, name="project-index-revision-export", daemon=True)
        thread.start()
        return thread

    def _checkout_unit(self, repo_root: Path, commit: str) -> None:
        """裏の処理の 1 件として commit を書き出し、止まった書き出しはログに残して戻る。"""
        with self.gate.unit():
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
                from project_index import poc_timing

                with poc_timing.span("archive", repo=str(repo_root), commit=commit):
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
                    poc_timing.span("extract", repo=str(repo_root), commit=commit),
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

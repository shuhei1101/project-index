"""クローンの更新と、移し替えの要否の確かめ。"""

from __future__ import annotations

import logging
import subprocess
import tomllib
from typing import TYPE_CHECKING

from project_index.features.lifecycle.types import COMMAND_TIMEOUT_SEC, UpdateResult
from project_index.shared.errors import RestartInProgressError, UpdateFailedError
from project_index.shared.version import RUNNING_VERSION

if TYPE_CHECKING:
    from pathlib import Path

    from project_index.features.lifecycle.control import RestartControl

logger = logging.getLogger(__name__)

STDERR_TAIL_CHARS = 500


def _run(argv: list[str], *, cwd: Path) -> str:
    """クローンで 1 つのコマンドを打ち切りつきで実行し、標準出力を返す。"""
    command = " ".join(argv)
    try:
        result = subprocess.run(  # noqa: S603
            argv, cwd=cwd, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SEC
        )
    except FileNotFoundError as error:
        raise UpdateFailedError(
            message=f"{command}: コマンドが見つかりません", command=argv
        ) from error
    except subprocess.TimeoutExpired as error:
        raise UpdateFailedError(
            message=f"{command}: {COMMAND_TIMEOUT_SEC} 秒で打ち切りました", command=argv
        ) from error
    # 終了コードが 0 以外
    if result.returncode != 0:
        logger.error(
            "更新のコマンドが失敗した（%s・終了コード %s・%s）",
            command,
            result.returncode,
            result.stderr[-STDERR_TAIL_CHARS:],
        )
        raise UpdateFailedError(
            message=f"{command}: 終了コード {result.returncode}",
            command=argv,
            stderr=result.stderr,
        )
    return result.stdout


def update_clone(clone: Path, *, control: RestartControl) -> UpdateResult:
    """クローンを更新し、移し替えが要らなければ再起動を要求する。"""
    # 他の更新が進んでいるか、再起動を要求済みなら断る
    if not control.update_lock.acquire(blocking=False):
        raise RestartInProgressError(message="再起動か更新の途中です")
    try:
        if control.requested:
            raise RestartInProgressError(message="再起動か更新の途中です")
        return _update(clone, control)
    finally:
        control.update_lock.release()


def _update(clone: Path, control: RestartControl) -> UpdateResult:
    """更新の本体（`update_lock` を取った中で呼ぶ）。"""
    previous_version = RUNNING_VERSION
    before = _run(["git", "rev-parse", "HEAD"], cwd=clone).strip()
    logger.info("クローンを更新する（%s）", clone)
    _run(["git", "pull", "--ff-only"], cwd=clone)
    after = _run(["git", "rev-parse", "HEAD"], cwd=clone).strip()
    # 新しい commit が無ければ何もしない
    if before == after:
        return UpdateResult(
            previous_version=previous_version,
            version=previous_version,
            updated=False,
            migration_needed=False,
            restarting=False,
        )
    _run(["uv", "sync"], cwd=clone)
    with (clone / "pyproject.toml").open("rb") as file:
        version = str(tomllib.load(file)["project"]["version"])
    # 新しいコードで移し替えの要否を確かめる
    python = clone / ".venv" / "bin" / "python"
    plan = _run([str(python), "-m", "project_index", "migrate", "--plan"], cwd=clone)
    migration_needed = bool(plan.strip())
    if migration_needed:
        # 移し替えが要るときは、利用者が移し替えてから再起動する
        logger.warning("移し替えが要るため再起動しない（%s）", version)
    else:
        control.request()
    return UpdateResult(
        previous_version=previous_version,
        version=version,
        updated=True,
        migration_needed=migration_needed,
        restarting=not migration_needed,
    )

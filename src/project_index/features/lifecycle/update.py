"""クローンの更新と、移し替えの要否の確かめ。"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tomllib
from typing import TYPE_CHECKING

from project_index.features.lifecycle.types import (
    COMMAND_TIMEOUT_SEC,
    MDMARK_PACKAGE,
    MdmarkReinstallResult,
    UpdateResult,
)
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


def _reinstall_mdmark(mdmark_ref: str) -> MdmarkReinstallResult | None:
    """`PATH` に mdmark の CLI があれば `npm install -g` で入れ直し、結果を返す。"""
    if shutil.which("mdmark") is None:
        return None
    argv = ["npm", "install", "-g", f"{MDMARK_PACKAGE}#{mdmark_ref}"]
    command = " ".join(argv)
    logger.info("mdmark の CLI を入れ直す（%s）", mdmark_ref)
    error: str | None = None
    try:
        result = subprocess.run(  # noqa: S603
            argv, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SEC
        )
    except FileNotFoundError:
        error = f"{command}: コマンドが見つかりません"
    except subprocess.TimeoutExpired:
        error = f"{command}: {COMMAND_TIMEOUT_SEC} 秒で打ち切りました"
    else:
        if result.returncode != 0:
            error = (
                f"{command}: 終了コード {result.returncode}\n{result.stderr[-STDERR_TAIL_CHARS:]}"
            )
    if error is not None:
        logger.warning("mdmark の CLI を入れ直せなかった（%s）", error)
    return MdmarkReinstallResult(ref=mdmark_ref, reinstalled=error is None, error=error)


def update_clone(clone: Path, *, control: RestartControl, mdmark_ref: str) -> UpdateResult:
    """クローンを更新し、移し替えが要らなければ再起動を要求する。"""
    # 他の更新が進んでいるか、再起動を要求済みなら断る
    if not control.update_lock.acquire(blocking=False):
        raise RestartInProgressError(message="再起動か更新の途中です")
    try:
        if control.requested:
            raise RestartInProgressError(message="再起動か更新の途中です")
        return _update(clone, control, mdmark_ref)
    finally:
        control.update_lock.release()


def _update(clone: Path, control: RestartControl, mdmark_ref: str) -> UpdateResult:
    """更新の本体（`update_lock` を取った中で呼ぶ）。"""
    previous_version = RUNNING_VERSION
    before = _run(["git", "rev-parse", "HEAD"], cwd=clone).strip()
    logger.info("クローンを更新する（%s）", clone)
    _run(["git", "pull", "--ff-only"], cwd=clone)
    after = _run(["git", "rev-parse", "HEAD"], cwd=clone).strip()
    # 新しい commit が無ければ mdmark の CLI だけを入れ直す
    if before == after:
        return UpdateResult(
            previous_version=previous_version,
            version=previous_version,
            updated=False,
            migration_needed=False,
            restarting=False,
            mdmark=_reinstall_mdmark(mdmark_ref),
        )
    _run(["uv", "sync"], cwd=clone)
    with (clone / "pyproject.toml").open("rb") as file:
        version = str(tomllib.load(file)["project"]["version"])
    # 新しいコードで移し替えの要否を確かめる
    python = clone / ".venv" / "bin" / "python"
    plan = _run([str(python), "-m", "project_index", "migrate", "--plan"], cwd=clone)
    migration_needed = bool(plan.strip())
    mdmark = _reinstall_mdmark(mdmark_ref)
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
        mdmark=mdmark,
    )

"""動いているプロセスが起動した時点の project-index のバージョンと、クローンの HEAD の読み取り。"""

from __future__ import annotations

import logging
import subprocess
from importlib.metadata import version
from typing import TYPE_CHECKING

from project_index import DIST_NAME

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# 更新で配布のメタデータが入れ替わっても変わらないよう、読み込んだ時点の値を持つ
RUNNING_VERSION = version(DIST_NAME)
# ローカルの `git rev-parse` は 1 秒かからない。止まっても起動を長く待たせないため短い上限で打ち切る
HEAD_READ_TIMEOUT_SEC = 10


def read_head(clone: Path) -> str | None:
    """クローンの HEAD の commit を読み、読めなければ None を返す。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=clone,
            capture_output=True,
            text=True,
            timeout=HEAD_READ_TIMEOUT_SEC,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.warning("クローンの HEAD を読めない（%s・%s）", clone, error)
        return None
    # git のリポジトリでない 等
    if result.returncode != 0:
        logger.warning("クローンの HEAD を読めない（%s・%s）", clone, result.stderr.strip())
        return None
    return result.stdout.strip()

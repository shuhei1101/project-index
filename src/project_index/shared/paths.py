"""作業場所の glob の照合とパスの正規化。"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def normalize_path(path: str | Path) -> Path:
    """`~` の展開・`..` の解決・末尾の `/` の除去をした絶対パスにする。"""
    return Path(os.path.abspath(Path(path).expanduser()))


def match_glob(path: Path, patterns: Sequence[str], *, base: Path | None = None) -> bool:
    """作業場所のパスが glob の 1 つに当たるかを返す。"""
    target = PurePosixPath(normalize_path(path).as_posix())
    for pattern in patterns:
        expanded = Path(pattern).expanduser()
        if not expanded.is_absolute():
            # 基準が無い相対パスの glob は当たらない
            if base is None:
                continue
            expanded = base / expanded
        # `..` を解くが、末尾の `**` と `*` は文字列のまま残す
        glob = PurePosixPath(os.path.normpath(expanded.as_posix()))
        if target.full_match(glob.as_posix()):
            return True
        # `/**` で終わる glob はそのフォルダ自身にも当たる
        if glob.name == "**" and target.full_match(glob.parent.as_posix()):
            return True
    return False

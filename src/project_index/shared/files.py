"""一時ファイルからのファイルの置き換え。"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def replace_file(path: Path, content: str) -> None:
    """同じフォルダの一時ファイルに書いてから置き換える。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        except OSError:
            temp.unlink(missing_ok=True)
            raise
    try:
        # 既にあるファイルのパーミッションを引き継ぐ
        if path.exists():
            shutil.copymode(path, temp)
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)
        raise

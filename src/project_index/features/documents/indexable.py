"""たどるフォルダと、管理用の YAML に載せるファイルの判定。"""

from __future__ import annotations

import os
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from project_index.features.sources.types import DocumentTable

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

# ファイルをたどるときに中に入らないフォルダ名
SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv"})
# ファイルをたどるときに中に入らないフォルダの `root` からのパス（配信元の設定の `worktrees` の既定と同じ場所）
SKIP_PATHS = frozenset({".claude/worktrees"})
# ファイルをたどるときに返さないファイル名（ワークツリーとサブモジュールの、本体を指す 1 行の `.git`）
SKIP_FILES = frozenset({".git"})
# その端末だけで使用する（Git に無視させる）ファイルの名前
LOCAL_FILE_PATTERN = "*.local.*"
# 先頭のこのバイト数に NUL バイトがあればバイナリとみなす
BINARY_SNIFF_BYTES = 8192


def walk_files(root: Path, *, start: str = ".") -> Iterator[str]:
    """フォルダの配下のファイルを、たどらないフォルダを飛ばして `root` からのパスで返す。"""
    # シンボリックリンクのフォルダには os.walk（followlinks=False）が入らないので、
    # フォルダごとに os.path.islink（lstat）を呼ばない
    for folder, dirnames, filenames in os.walk(root / start, followlinks=False):
        relative_folder = Path(folder).relative_to(root).as_posix()
        # たどらない名前・パスのフォルダは中に入らない
        dirnames[:] = [
            name
            for name in dirnames
            if name not in SKIP_DIRS and _join(relative_folder, name) not in SKIP_PATHS
        ]
        for name in filenames:
            # ワークツリーの `.git` などのファイルは返さない
            if name in SKIP_FILES:
                continue
            yield _join(relative_folder, name)


def walk_tree(root: Path) -> tuple[list[str], dict[str, int]]:
    """中をたどるファイルの一覧と、たどったフォルダごとの更新日時（`st_mtime_ns`）を返す。"""
    files: list[str] = []
    folders: dict[str, int] = {}
    for folder, dirnames, filenames in os.walk(root, followlinks=False):
        relative_folder = Path(folder).relative_to(root).as_posix()
        # フォルダの中のファイルの追加・削除・改名で、フォルダの更新日時が変わる
        try:
            folders[relative_folder] = os.stat(folder).st_mtime_ns
        except OSError:
            # たどる途中で無くなったフォルダは記録しない
            continue
        # たどらない名前・パスのフォルダは中に入らない（中をたどるファイルの列挙と同じ）
        dirnames[:] = [
            name
            for name in dirnames
            if name not in SKIP_DIRS and _join(relative_folder, name) not in SKIP_PATHS
        ]
        # ワークツリーの `.git` などのファイルは返さない（中をたどるファイルの列挙と同じ）
        files.extend(_join(relative_folder, name) for name in filenames if name not in SKIP_FILES)
    return files, folders


def _join(relative_folder: str, name: str) -> str:
    """`root` からのフォルダのパスと名前をつなぐ（`root` 直下は名前だけ）。"""
    return name if relative_folder == "." else f"{relative_folder}/{name}"


def is_excluded_file(root: Path, path: str) -> bool:
    """ファイルが管理用の YAML に載せない除外の条件に当たるかを返す。"""
    # その端末だけで使用するファイルの名前か
    if fnmatch(PurePosixPath(path).name, LOCAL_FILE_PATTERN):
        return True
    try:
        # 空のファイルか
        if (root / path).stat().st_size == 0:
            return True
        with (root / path).open("rb") as file:
            head = file.read(BINARY_SNIFF_BYTES)
    except OSError:
        # 読めないファイルは除外せず、読み込みの問題として別に出す
        return False
    # 先頭に NUL バイトがあるバイナリか
    return b"\x00" in head


def indexable_files(
    root: Path,
    paths: Sequence[str],
    *,
    exclude: Sequence[str] = (),
    exclude_paths: Sequence[str] = (),
) -> list[str]:
    """範囲の glob に当たるファイルのうち、除外の名前・除外のパス・除外の条件に当たらないものを返す。"""
    # loader が walk_files を使うため、循環を避けて呼ぶ時点で取り込む
    from project_index.features.documents.loader import collect_files

    table = DocumentTable(id="files", paths=list(paths), schema_path="", exclude=list(exclude))
    return [
        path
        for path in collect_files(root, table)
        # 除外のパスは文書の行の paths と同じく、パス全体で当てる
        if not any(PurePosixPath(path).full_match(pattern) for pattern in exclude_paths)
        and not is_excluded_file(root, path)
    ]

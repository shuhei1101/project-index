"""たどるフォルダと、管理用の YAML に載せるファイルの判定。"""

from __future__ import annotations

import ast
import os
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from project_index.features.sources.types import DocumentTable

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

# ファイルをたどるときに中に入らないフォルダ名
SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv"})
# ファイルをたどるときに中に入らないフォルダの `root` からのパス（配信元の設定の `worktrees` の既定と同じ場所）
SKIP_PATHS = frozenset({".claude/worktrees"})
# 依存のロックファイルとみなすファイル名（末尾が `.lock` のファイルもロックとみなす）
LOCK_FILES = frozenset(
    {"package-lock.json", "pnpm-lock.yaml", "go.sum", "bun.lockb", "npm-shrinkwrap.json"}
)
# パスの途中にこの名前のフォルダがあるファイルを、ベンダーのコードか生成物とみなす
VENDOR_DIRS = frozenset({"vendor", "third_party", "generated", "__generated__", "dist"})
# ファイル名がこの末尾のファイルを生成物とみなす
GENERATED_SUFFIXES = ("_pb2.py", "_pb2_grpc.py", ".min.js", ".min.css", ".map")
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
            yield _join(relative_folder, name)


def _join(relative_folder: str, name: str) -> str:
    """`root` からのフォルダのパスと名前をつなぐ（`root` 直下は名前だけ）。"""
    return name if relative_folder == "." else f"{relative_folder}/{name}"


def is_excluded_file(root: Path, path: str) -> bool:
    """ファイルが管理用の YAML に載せない除外の条件に当たるかを返す。"""
    target = PurePosixPath(path)
    # ベンダー・生成物のフォルダの下にあるか
    if VENDOR_DIRS.intersection(target.parts[:-1]):
        return True
    # ロックファイルか
    if target.name in LOCK_FILES or target.name.endswith(".lock"):
        return True
    # 生成物のファイル名か
    if target.name.endswith(GENERATED_SUFFIXES):
        return True
    try:
        with (root / path).open("rb") as file:
            head = file.read(BINARY_SNIFF_BYTES)
        # 先頭に NUL バイトがあるバイナリか
        if b"\x00" in head:
            return True
        if target.name == "__init__.py":
            return _is_reexport_only((root / path).read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError:
        # 読めないファイルは除外せず、読み込みの問題として別に出す
        return False
    return False


def _is_reexport_only(source: str) -> bool:
    """文が空か、import 文・先頭の docstring・`__all__` への代入だけかを返す。"""
    try:
        statements = ast.parse(source).body
    except SyntaxError:
        return False
    for index, statement in enumerate(statements):
        if isinstance(statement, ast.Import | ast.ImportFrom):
            continue
        if index == 0 and _is_docstring(statement):
            continue
        if _is_all_assignment(statement):
            continue
        return False
    return True


def _is_docstring(statement: ast.stmt) -> bool:
    """文字列だけの式（docstring）かを返す。"""
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _is_all_assignment(statement: ast.stmt) -> bool:
    """`__all__` への代入かを返す。"""
    if isinstance(statement, ast.Assign):
        targets = statement.targets
    elif isinstance(statement, ast.AnnAssign):
        targets = [statement.target]
    else:
        return False
    return all(isinstance(target, ast.Name) and target.id == "__all__" for target in targets)


def indexable_files(root: Path, paths: Sequence[str], *, exclude: Sequence[str] = ()) -> list[str]:
    """範囲の glob に当たるファイルのうち、除外の名前と除外の条件に当たらないものを返す。"""
    # loader が walk_files を使うため、循環を避けて呼ぶ時点で取り込む
    from project_index.features.documents.loader import collect_files

    table = DocumentTable(id="files", paths=list(paths), schema_path="", exclude=list(exclude))
    return [path for path in collect_files(root, table) if not is_excluded_file(root, path)]

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from project_index.features.documents.indexable import indexable_files, is_excluded_file, walk_files


def test_walk_files(tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]) -> None:
    """たどらないフォルダを飛ばす（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "a/x.md": "# x\n",
            ".git/c": "c\n",
            "node_modules/m.js": "m\n",
            ".claude/worktrees/wt/y.md": "# y\n",
            ".claude/z.md": "# z\n",
        },
    )
    # 実行
    result = sorted(walk_files(tmp_path))
    # 検証
    assert result == [".claude/z.md", "a/x.md"]


def test_walk_files_when_start_given(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """始めるフォルダの配下だけをたどる（正常系）。"""
    # 準備
    write_files(tmp_path, {"a/x.md": "# x\n", "b/y.md": "# y\n"})
    # 実行
    result = sorted(walk_files(tmp_path, start="a"))
    # 検証
    assert result == ["a/x.md"]


def test_walk_files_when_symlink_folder(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """シンボリックリンクのフォルダをたどらない（正常系）。"""
    # 準備
    write_files(tmp_path, {"a/x.md": "# x\n"})
    (tmp_path / "l").symlink_to(tmp_path / "a", target_is_directory=True)
    # 実行
    result = sorted(walk_files(tmp_path))
    # 検証
    assert result == ["a/x.md"]


def test_is_excluded_file_when_lock(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """ロックファイル（正常系）。"""
    # 準備
    write_files(tmp_path, {"uv.lock": "version = 1\n", "package-lock.json": "{}\n"})
    # 実行
    uv_lock = is_excluded_file(tmp_path, "uv.lock")
    package_lock = is_excluded_file(tmp_path, "package-lock.json")
    # 検証
    assert uv_lock is True
    assert package_lock is True


def test_is_excluded_file_when_vendor(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """ベンダー・生成物のフォルダの下（正常系）。"""
    # 準備
    write_files(tmp_path, {"src/vendor/a.py": "a = 1\n", "web/dist/app.js": "var a;\n"})
    # 実行
    vendor = is_excluded_file(tmp_path, "src/vendor/a.py")
    dist = is_excluded_file(tmp_path, "web/dist/app.js")
    # 検証
    assert vendor is True
    assert dist is True


def test_is_excluded_file_when_generated_suffix(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """生成物のファイル名（正常系）。"""
    # 準備
    write_files(tmp_path, {"api_pb2.py": "a = 1\n", "app.min.js": "var a;\n"})
    # 実行
    protobuf = is_excluded_file(tmp_path, "api_pb2.py")
    minified = is_excluded_file(tmp_path, "app.min.js")
    # 検証
    assert protobuf is True
    assert minified is True


def test_is_excluded_file_when_binary(tmp_path: Path) -> None:
    """NUL バイトを持つファイル（正常系）。"""
    # 準備
    (tmp_path / "logo.png").write_bytes(b"\x00PNG\r\n")
    # 実行
    result = is_excluded_file(tmp_path, "logo.png")
    # 検証
    assert result is True


def test_is_excluded_file_when_reexport_init(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """空・再エクスポートだけの `__init__.py`（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "a/__init__.py": "",
            "b/__init__.py": '"""公開する型。"""\n\nfrom .x import y\n\n__all__ = ["y"]\n',
        },
    )
    # 実行
    empty = is_excluded_file(tmp_path, "a/__init__.py")
    reexport = is_excluded_file(tmp_path, "b/__init__.py")
    # 検証
    assert empty is True
    assert reexport is True


def test_is_excluded_file_when_init_has_logic(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """処理を持つ `__init__.py` は載せる（正常系）。"""
    # 準備
    write_files(tmp_path, {"c/__init__.py": "def f() -> None: ...\n"})
    # 実行
    result = is_excluded_file(tmp_path, "c/__init__.py")
    # 検証
    assert result is False


def test_is_excluded_file_when_source(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """通常のコードは載せる（正常系）。"""
    # 準備
    write_files(tmp_path, {"src/a.py": "a = 1\n", "docs/a.md": "# a\n"})
    # 実行
    code = is_excluded_file(tmp_path, "src/a.py")
    document = is_excluded_file(tmp_path, "docs/a.md")
    # 検証
    assert code is False
    assert document is False


def test_indexable_files(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """除外の条件に当たるファイルを除く（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "src/a.py": "a = 1\n",
            "src/b.py": "b = 2\n",
            "src/pkg/__init__.py": "",
            "src/uv.lock": "version = 1\n",
            ".claude/worktrees/wt/src/c.py": "c = 3\n",
        },
    )
    # 実行
    result = indexable_files(tmp_path, ["**"])
    # 検証
    assert result == ["src/a.py", "src/b.py"]


def test_indexable_files_when_exclude_given(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """除外の名前に当たるファイルも除く（正常系）。"""
    # 準備
    write_files(tmp_path, {"src/a.py": "a = 1\n", "src/b.py": "b = 2\n"})
    # 実行
    result = indexable_files(tmp_path, ["src/**"], exclude=["b.py"])
    # 検証
    assert result == ["src/a.py"]

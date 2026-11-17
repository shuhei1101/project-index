from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.documents.indexable import (
    indexable_files,
    is_excluded_file,
    walk_files,
    walk_tree,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


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


def test_is_excluded_file_when_generated_and_lock(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """生成物・ロック・ベンダーのコードは載せる（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "uv.lock": "version = 1\n",
            "package-lock.json": "{}\n",
            "src/vendor/a.py": "a = 1\n",
            "web/dist/app.js": "var a;\n",
            "api_pb2.py": "a = 1\n",
            "app.min.js": "var a;\n",
        },
    )
    # 実行
    uv_lock = is_excluded_file(tmp_path, "uv.lock")
    package_lock = is_excluded_file(tmp_path, "package-lock.json")
    vendor = is_excluded_file(tmp_path, "src/vendor/a.py")
    dist = is_excluded_file(tmp_path, "web/dist/app.js")
    protobuf = is_excluded_file(tmp_path, "api_pb2.py")
    minified = is_excluded_file(tmp_path, "app.min.js")
    # 検証
    assert uv_lock is False
    assert package_lock is False
    assert vendor is False
    assert dist is False
    assert protobuf is False
    assert minified is False


def test_is_excluded_file_when_local_name(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """`*.local.*` の名前のファイル（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "files.local.yaml": "files: []\n",
            "src/settings.local.json": "{}\n",
            "local.py": "a = 1\n",
            "docs/locale.md": "# locale\n",
        },
    )
    # 実行
    files_local = is_excluded_file(tmp_path, "files.local.yaml")
    settings_local = is_excluded_file(tmp_path, "src/settings.local.json")
    local_py = is_excluded_file(tmp_path, "local.py")
    locale_md = is_excluded_file(tmp_path, "docs/locale.md")
    # 検証
    assert files_local is True
    assert settings_local is True
    assert local_py is False
    assert locale_md is False


def test_is_excluded_file_when_binary(tmp_path: Path) -> None:
    """NUL バイトを持つファイル（正常系）。"""
    # 準備
    (tmp_path / "logo.png").write_bytes(b"\x00PNG\r\n")
    # 実行
    result = is_excluded_file(tmp_path, "logo.png")
    # 検証
    assert result is True


def test_is_excluded_file_when_empty(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """空のファイル（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "a/__init__.py": "",
            "b/__init__.py": '"""公開する型。"""\n\nfrom .x import y\n',
        },
    )
    # 実行
    empty = is_excluded_file(tmp_path, "a/__init__.py")
    reexport = is_excluded_file(tmp_path, "b/__init__.py")
    # 検証
    assert empty is True
    assert reexport is False


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
    assert result == ["src/a.py", "src/b.py", "src/uv.lock"]


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


def test_walk_tree(tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]) -> None:
    """ファイルとフォルダの更新日時（正常系）。"""
    # 準備
    write_files(tmp_path, {"a.yaml": "a\n", "rules/b.yaml": "b\n", "node_modules/x.js": "x\n"})
    (tmp_path / "empty").mkdir()
    expected_folders = {
        ".": tmp_path.stat().st_mtime_ns,
        "rules": (tmp_path / "rules").stat().st_mtime_ns,
        "empty": (tmp_path / "empty").stat().st_mtime_ns,
    }
    # 実行
    files, folders = walk_tree(tmp_path)
    # 検証
    assert sorted(files) == ["a.yaml", "rules/b.yaml"]
    assert folders == expected_folders

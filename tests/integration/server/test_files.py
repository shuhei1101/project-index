from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from project_index.__main__ import main

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _listing(folder: Path) -> dict[str, bytes]:
    """フォルダの下のファイルのパスと中身を集める。"""
    return {
        str(path.relative_to(folder)): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def range_folder(tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]) -> Path:
    """除外の条件に当たるファイルとワークツリーのファイルを持つ、配信元ではないフォルダを作る。"""
    folder = tmp_path / "range"
    write_files(
        folder,
        {
            "src/a.py": "a = 1\n",
            "src/b.py": "b = 2\n",
            "src/pkg/__init__.py": "",
            "src/uv.lock": "version = 1\n",
            ".claude/worktrees/wt/src/c.py": "c = 3\n",
        },
    )
    (folder / "src" / "logo.png").write_bytes(b"\x00PNG\r\n")
    return folder


def test_normal(range_folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """除外の条件に当たるファイルを除いた一覧を出す（正常系）。"""
    # 準備
    before = _listing(range_folder)
    # 実行
    code = main(["files", "--root", str(range_folder), "--paths", "**"])
    # 検証
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "src/a.py\nsrc/b.py\n"
    assert _listing(range_folder) == before


def test_normal_when_exclude_given(range_folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--exclude` に当たるファイルも外す（正常系）。"""
    # 実行
    code = main(["files", "--root", str(range_folder), "--paths", "src/**", "--exclude", "b.py"])
    # 検証
    assert code == 0
    assert capsys.readouterr().out == "src/a.py\n"


def test_error_when_root_not_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--root` が無いと終了コード 2 で終える（異常系）。"""
    # 準備
    missing = tmp_path / "missing"
    # 実行
    code = main(["files", "--root", str(missing), "--paths", "src/**"])
    # 検証
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert str(missing) in captured.err

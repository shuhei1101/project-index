from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from project_index.shared.files import replace_file

if TYPE_CHECKING:
    from pathlib import Path


def test_replace_file(tmp_path: Path) -> None:
    """内容とパーミッションを保って置き換える（正常系）。"""
    # 準備
    target = tmp_path / "settings.yaml"
    target.write_text("old\n", encoding="utf-8")
    target.chmod(0o600)
    # 実行
    replace_file(target, "a: 1\n")
    # 検証
    assert target.read_text(encoding="utf-8") == "a: 1\n"
    assert target.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob("*.tmp"))


def test_replace_file_when_new_folder(tmp_path: Path) -> None:
    """フォルダを作る（正常系）。"""
    # 準備
    target = tmp_path / "new" / "deep" / "a.yaml"
    # 実行
    replace_file(target, "a: 1\n")
    # 検証
    assert target.read_text(encoding="utf-8") == "a: 1\n"


def test_replace_file_when_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """置き換えに失敗すると一時ファイルを残さない（異常系）。"""
    # 準備
    target = tmp_path / "a.yaml"
    target.write_text("old\n", encoding="utf-8")

    def failing_replace(src: str, dst: str) -> None:
        msg = "replace failed"
        raise OSError(msg)

    monkeypatch.setattr(os, "replace", failing_replace)
    # 実行・検証
    with pytest.raises(OSError, match="replace failed"):
        replace_file(target, "new\n")
    assert target.read_text(encoding="utf-8") == "old\n"
    assert not list(tmp_path.glob("*.tmp"))

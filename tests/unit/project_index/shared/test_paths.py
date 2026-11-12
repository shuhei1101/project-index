from __future__ import annotations

from pathlib import Path

from project_index.shared.paths import match_glob, normalize_path


def test_match_glob() -> None:
    """`/**` の無いパスはそのフォルダだけ（正常系）。"""
    # 実行
    exact = match_glob(Path("/r/a"), ["/r/a"])
    child = match_glob(Path("/r/a/b"), ["/r/a"])
    # 検証
    assert exact is True
    assert child is False


def test_match_glob_when_recursive() -> None:
    """`/**` は自分と中に当たる（正常系）。"""
    # 実行
    itself = match_glob(Path("/r/a"), ["/r/a/**"])
    nested = match_glob(Path("/r/a/b/c"), ["/r/a/**"])
    # 検証
    assert itself is True
    assert nested is True


def test_match_glob_when_relative() -> None:
    """相対パスを基準で解く（正常系）。"""
    # 実行
    result = match_glob(Path("/r/.claude/worktrees/x"), ["./.claude/worktrees/*"], base=Path("/r"))
    # 検証
    assert result is True


def test_match_glob_when_relative_without_base() -> None:
    """基準が無い相対パス（正常系）。"""
    # 実行
    result = match_glob(Path("/r/.claude/worktrees/x"), ["./.claude/worktrees/*"], base=None)
    # 検証
    assert result is False


def test_normalize_path() -> None:
    """`..` と末尾の `/` を除く（正常系）。"""
    # 実行
    result = normalize_path("/r/a/../b/")
    # 検証
    assert result == Path("/r/b")

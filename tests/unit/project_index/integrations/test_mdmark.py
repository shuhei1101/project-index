from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from project_index.integrations.mdmark import (
    MdmarkFinding,
    MdmarkUnavailableError,
    check_markdown,
    parse_check_output,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.fixture
def fake_mdmark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Path]:
    """渡した Python のコードを本体にした `mdmark` を、PATH の唯一のフォルダに置く関数を返す。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))

    def _make(code: str) -> Path:
        script = bin_dir / "mdmark"
        script.write_text(f"#!{sys.executable}\n{code}\n", encoding="utf-8")
        script.chmod(0o755)
        return script

    return _make


def test_check_markdown(fake_mdmark: Callable[[str], Path], tmp_path: Path) -> None:
    """ずれが無い（正常系）。"""
    # 準備
    fake_mdmark(
        "import pathlib, sys\n"
        "pathlib.Path('args.txt').write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n"
        "pathlib.Path('stdin.txt').write_text(sys.stdin.read(), encoding='utf-8')\n"
        "print('ずれ 0 件')"
    )
    # 実行
    result = check_markdown("# 見出し\n", cwd=tmp_path, timeout_sec=10)
    # 検証
    assert result == []
    assert (tmp_path / "args.txt").read_text(encoding="utf-8") == "check --text -"
    assert (tmp_path / "stdin.txt").read_text(encoding="utf-8") == "# 見出し\n"


def test_check_markdown_when_findings(fake_mdmark: Callable[[str], Path], tmp_path: Path) -> None:
    """ずれがある（正常系）。"""
    # 準備
    fake_mdmark(
        "import sys\n"
        "sys.stdin.read()\n"
        "print('-:3: diagram_invalid: A')\n"
        "print('-:1: unknown_mark: B')\n"
        "print('ずれ 2 件')\n"
        "sys.exit(1)"
    )
    # 実行
    result = check_markdown("x", cwd=tmp_path, timeout_sec=10)
    # 検証
    assert result == [
        MdmarkFinding(line=3, kind="diagram_invalid", message="A"),
        MdmarkFinding(line=1, kind="unknown_mark", message="B"),
    ]


def test_check_markdown_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI が無い（異常系）。"""
    # 準備
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    # 実行・検証
    with pytest.raises(
        MdmarkUnavailableError, match="mdmark の CLI が PATH に見つかりません"
    ) as exc_info:
        check_markdown("x", cwd=tmp_path, timeout_sec=10)
    assert exc_info.value.continuable is False


def test_check_markdown_when_timeout(fake_mdmark: Callable[[str], Path], tmp_path: Path) -> None:
    """制限時間を超える（異常系）。"""
    # 準備
    fake_mdmark("import time\ntime.sleep(5)")
    # 実行・検証
    with pytest.raises(MdmarkUnavailableError, match="制限時間") as exc_info:
        check_markdown("x", cwd=tmp_path, timeout_sec=0.2)
    assert exc_info.value.continuable is False


def test_check_markdown_when_no_summary(fake_mdmark: Callable[[str], Path], tmp_path: Path) -> None:
    """結果を出さずに終わる（異常系）。"""
    # 準備
    fake_mdmark("import sys\nprint('unknown option --text', file=sys.stderr)\nsys.exit(1)")
    # 実行・検証
    with pytest.raises(MdmarkUnavailableError, match="結果を出さずに") as exc_info:
        check_markdown("x", cwd=tmp_path, timeout_sec=10)
    assert exc_info.value.continuable is True
    assert "unknown option --text" in exc_info.value.reason


def test_parse_check_output() -> None:
    """ずれと件数の行（正常系）。"""
    # 準備
    stdout = "-:3: diagram_invalid: 図の定義を読めません: x\nずれ 1 件\n"
    # 実行
    result = parse_check_output(stdout)
    # 検証
    assert result == [
        MdmarkFinding(line=3, kind="diagram_invalid", message="図の定義を読めません: x")
    ]


def test_parse_check_output_when_no_summary() -> None:
    """件数の行が無い（正常系）。"""
    # 準備
    stdout = "-:3: diagram_invalid: x\n"
    # 実行
    result = parse_check_output(stdout)
    # 検証
    assert result is None

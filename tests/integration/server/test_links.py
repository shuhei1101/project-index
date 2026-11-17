from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from project_index.__main__ import main

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest


def _lines(output: str) -> list[dict[str, Any]]:
    """1 行 1 ファイルの JSON を読む。"""
    return [json.loads(line) for line in output.splitlines()]


def test_normal(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Markdown のリンクと YAML の値のパスから、指す先のファイルを出す（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "docs/guide.md": (
                "# 使い方\n\n"
                "[API](./api.md) と [外](https://example.com) と [自分](#見出し)\n\n"
                "実装は `src/tasks/util.py` にある。\n"
            ),
            "docs/api.md": "# API\n",
            "design/util.yaml": "description: 実装はsrc/tasks/util.pyにある\nnote: src/none.py\n",
            "src/tasks/util.py": "def run() -> None:\n    pass\n",
        },
    )
    # 実行
    code = main(["links", "--root", str(tmp_path), "--paths", "**/*"])
    # 検証
    assert code == 0
    assert _lines(capsys.readouterr().out) == [
        {"path": "design/util.yaml", "targets": [{"path": "src/tasks/util.py", "via": "path"}]},
        {
            "path": "docs/guide.md",
            "targets": [
                {"path": "docs/api.md", "via": "link"},
                {"path": "src/tasks/util.py", "via": "path"},
            ],
        },
    ]


def test_error_when_root_not_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--root` が無いと終了コード 2 で終える（異常系）。"""
    # 準備
    missing = tmp_path / "missing"
    # 実行
    code = main(["links", "--root", str(missing), "--paths", "**/*"])
    # 検証
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert str(missing) in captured.err

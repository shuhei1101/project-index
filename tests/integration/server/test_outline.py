from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from project_index.__main__ import main

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

GUIDE_MD = (
    "# 使い方\n\n配信元を追加する手順を説明する。\n\n"
    "## 準備\n\n端末の設定を用意する。\n\n## 登録\n\n配信元を登録する。\n"
)
LOG_MD = "# ログ\n\n```text\n" + "".join(f"line {i}\n" for i in range(12)) + "```\n"
EN_MD = "# Usage\n\nThis guide explains the steps.\n\n## Setup\n\nPrepare the config.\n"
TASKS_PY = '''"""タスク。

タスクの保存を受け持つ。
"""

import yaml


def save() -> None:
    """保存する。"""


class Task:
    """タスク。"""
'''


def _lines(output: str) -> list[dict[str, Any]]:
    """1 行 1 ファイルの JSON を読む。"""
    return [json.loads(line) for line in output.splitlines()]


def test_normal(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """1 ファイル 1 行の JSON と次の段階へ進むかを出す（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "docs/guide.md": GUIDE_MD,
            "docs/log.md": LOG_MD,
            "docs/en.md": EN_MD,
            "src/tasks.py": TASKS_PY,
        },
    )
    # 実行
    code = main(["outline", "--root", str(tmp_path), "--paths", "**"])
    # 検証
    rows = {row["path"]: row for row in _lines(capsys.readouterr().out)}
    assert code == 0
    assert list(rows) == ["docs/en.md", "docs/guide.md", "docs/log.md", "src/tasks.py"]
    assert rows["docs/guide.md"]["next_stage"] is False
    assert rows["docs/log.md"]["next_stage"] is True
    assert {"few_headings", "mostly_code"} <= set(rows["docs/log.md"]["reasons"])
    assert rows["docs/en.md"]["next_stage"] is True
    assert "not_japanese" in rows["docs/en.md"]["reasons"]
    tasks = rows["src/tasks.py"]
    assert tasks["existing_description"]["source"] == "docstring"
    assert tasks["functions"] == ["save"]
    assert tasks["classes"] == ["Task"]
    assert tasks["imports"] == ["yaml"]
    assert tasks["next_stage"] is False


def test_normal_when_front_matter_given(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """フロントマターの説明を既に持つ説明として出す（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "docs/a.md": (
                "---\ntitle: 手順\ndescription: 配信元を追加する手順\n# 見出しではない\n---\n"
                "# 手順\n\n## 準備\n\n本文。\n"
            )
        },
    )
    # 実行
    code = main(["outline", "--root", str(tmp_path), "--paths", "**"])
    # 検証
    (row,) = _lines(capsys.readouterr().out)
    assert code == 0
    assert row["existing_description"] == {
        "source": "front_matter",
        "title": "手順",
        "description": "配信元を追加する手順",
    }
    assert row["headings"] == ["# 手順", "## 準備"]


def test_error_when_root_not_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--root` が無いと終了コード 2 で終える（異常系）。"""
    # 準備
    missing = tmp_path / "missing"
    # 実行
    code = main(["outline", "--root", str(missing), "--paths", "**"])
    # 検証
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert str(missing) in captured.err

from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING, Any

import pytest

from project_index.shared.version import HEAD_READ_TIMEOUT_SEC, read_head

if TYPE_CHECKING:
    from pathlib import Path


def test_read_head(tmp_path: Path) -> None:
    """HEAD の commit を返す（正常系）。"""
    # 準備
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "first",
        ],
        check=True,
    )
    expected = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    # 実行
    result = read_head(tmp_path)
    # 検証
    assert result == expected
    assert len(result) == 40


def test_read_head_when_not_repository(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """git のリポジトリでなければ None（正常系）。"""
    # 準備
    caplog.set_level(logging.WARNING, logger="project_index.shared.version")
    # 実行
    result = read_head(tmp_path)
    # 検証
    assert result is None
    assert len([record for record in caplog.records if record.levelno == logging.WARNING]) == 1


def test_read_head_when_git_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """git が無ければ None（正常系）。"""

    # 準備
    def missing(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr("project_index.shared.version.subprocess.run", missing)
    # 実行
    result = read_head(tmp_path)
    # 検証
    assert result is None


def test_read_head_when_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """打ち切ったら None（正常系）。"""
    # 準備
    timeouts: list[object] = []

    def slow(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        timeouts.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr("project_index.shared.version.subprocess.run", slow)
    # 実行
    result = read_head(tmp_path)
    # 検証
    assert result is None
    assert timeouts == [HEAD_READ_TIMEOUT_SEC]

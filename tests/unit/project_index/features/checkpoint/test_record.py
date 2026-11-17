from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from ruamel.yaml import YAML

from project_index.features.checkpoint.record import record_checkpoint
from project_index.features.checkpoint.types import FilesYamlNotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

FILES_YAML = "# 管理用の YAML\nfiles:\n  - path: src/tasks.py  # タスク\n    name: タスク\n"


def test_record_checkpoint(
    git_repo: Callable[..., Path],
    write_files: Callable[[Path, dict[str, str]], None],
    run_git: Callable[..., str],
) -> None:
    """Git の配信元で commit とハッシュを書く（正常系）。"""
    # 準備
    repo = git_repo({"files.yaml": FILES_YAML, "src/tasks.py": "a = 1\n"})
    head = run_git(repo, "rev-parse", "HEAD").strip()
    write_files(repo, {"src/tasks.py": "a = 2\n"})
    # 実行
    result = record_checkpoint(
        repo, "files.yaml", reviewed=["src/tasks.py"], now=datetime(2026, 11, 17, tzinfo=UTC)
    )
    # 検証
    text = (repo / "files.yaml").read_text(encoding="utf-8")
    data: dict[str, Any] = YAML(typ="safe").load(text)  # pyright: ignore[reportAssignmentType]
    digest = hashlib.sha256(b"a = 2\n").hexdigest()
    assert result.commit == head
    assert data["checkpoint"]["commit"] == head
    assert data["checkpoint"]["reviewed"] == [{"path": "src/tasks.py", "sha256": digest}]
    assert text.startswith(FILES_YAML)


def test_record_checkpoint_when_outside_git(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """Git 管理外で日時を書く（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {"files.yaml": "files: []\ncheckpoint:\n  checked_at: '2025-01-01T00:00:00+00:00'\n"},
    )
    # 実行
    record_checkpoint(tmp_path, "files.yaml", now=datetime(2026, 11, 17, tzinfo=UTC))
    # 検証
    data: dict[str, Any] = YAML(typ="safe").load(  # pyright: ignore[reportAssignmentType]
        (tmp_path / "files.yaml").read_text(encoding="utf-8")
    )
    assert data["checkpoint"] == {"checked_at": "2026-11-17T00:00:00+00:00"}


def test_record_checkpoint_when_files_yaml_missing(tmp_path: Path) -> None:
    """管理用の YAML が無い（異常系）。"""
    # 実行・検証
    with pytest.raises(FilesYamlNotFoundError):
        record_checkpoint(tmp_path, "files.yaml", now=datetime(2026, 11, 17, tzinfo=UTC))
    assert list(tmp_path.iterdir()) == []

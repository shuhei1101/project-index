from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ruamel.yaml import YAML

from project_index.__main__ import main

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

FILES_YAML = "# 管理用の YAML\nfiles:\n  - path: src/tasks.py  # タスク\n    name: タスク\n"


def _checkpoint(root: Path, *extra: str, files_yaml: str = "files.yaml") -> int:
    """`project-index checkpoint` を呼ぶ。"""
    return main(["checkpoint", "--root", str(root), "--files-yaml", files_yaml, *extra])


def _load(path: Path) -> dict[str, Any]:
    """YAML を読む。"""
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))  # pyright: ignore[reportReturnType]


def test_normal(
    git_repo: Callable[..., Path],
    write_files: Callable[[Path, dict[str, str]], None],
    run_git: Callable[..., str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Git の配信元で HEAD と見直したファイルのハッシュを記録する（正常系）。"""
    # 準備
    repo = git_repo({"files.yaml": FILES_YAML, "src/tasks.py": "a = 1\n"})
    head = run_git(repo, "rev-parse", "HEAD").strip()
    write_files(repo, {"src/tasks.py": "a = 2\n"})
    # 実行
    code = _checkpoint(repo, "--reviewed", "src/tasks.py")
    # 検証
    capsys.readouterr()
    text = (repo / "files.yaml").read_text(encoding="utf-8")
    data = _load(repo / "files.yaml")
    assert code == 0
    assert data["checkpoint"]["commit"] == head
    assert data["checkpoint"]["reviewed"] == [
        {"path": "src/tasks.py", "sha256": hashlib.sha256(b"a = 2\n").hexdigest()}
    ]
    assert text.startswith(FILES_YAML)


def test_normal_when_outside_git(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Git 管理外は呼んだ時刻を記録する（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {"files.yaml": "files: []\ncheckpoint:\n  checked_at: '2025-01-01T00:00:00+00:00'\n"},
    )
    called = datetime.now(UTC)
    # 実行
    code = _checkpoint(tmp_path)
    # 検証
    capsys.readouterr()
    checkpoint = _load(tmp_path / "files.yaml")["checkpoint"]
    assert code == 0
    assert list(checkpoint) == ["checked_at"]
    assert datetime.fromisoformat(checkpoint["checked_at"]) >= called.replace(microsecond=0)


def test_error_when_files_yaml_not_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """管理用の YAML が無いと終了コード 2 で終え、ファイルを作らない（異常系）。"""
    # 実行
    code = _checkpoint(tmp_path, files_yaml="missing.yaml")
    # 検証
    assert code == 2
    assert "missing.yaml" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_error_when_reviewed_file_not_found(
    git_repo: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """見直したファイルが無いと終了コード 2 で終え、管理用の YAML を書き換えない（異常系）。"""
    # 準備
    repo = git_repo({"files.yaml": FILES_YAML})
    # 実行
    code = _checkpoint(repo, "--reviewed", "missing.md")
    # 検証
    assert code == 2
    assert "missing.md" in capsys.readouterr().err
    assert (repo / "files.yaml").read_text(encoding="utf-8") == FILES_YAML

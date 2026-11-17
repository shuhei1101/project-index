from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from project_index.features.checkpoint.changed import find_changed, read_checkpoint
from project_index.features.checkpoint.types import BaseKind, FilesYamlNotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

ROWS_ABCD = "files:\n  - path: a.md\n  - path: b.md\n  - path: c.md\n  - path: d.md\n"


def test_read_checkpoint() -> None:
    """commit と見直し済みのファイル（正常系）。"""
    # 準備
    data = {"checkpoint": {"commit": "abc", "reviewed": [{"path": "a.md", "sha256": "00"}]}}
    # 実行
    result = read_checkpoint(data)
    # 検証
    assert result is not None
    assert result.commit == "abc"
    assert len(result.reviewed) == 1
    assert result.checked_at is None


def test_read_checkpoint_when_missing() -> None:
    """記録が無い（正常系）。"""
    # 実行
    result = read_checkpoint({"files": []})
    # 検証
    assert result is None


def test_read_checkpoint_when_invalid() -> None:
    """形が違う（異常系）。"""
    # 実行・検証
    with pytest.raises(ValueError, match="checked_at"):
        read_checkpoint({"checkpoint": {"checked_at": "x"}})


def test_find_changed(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    write_files: Callable[[Path, dict[str, str]], None],
    run_git: Callable[..., str],
) -> None:
    """記録した commit の後の commit と未 commit の変更（正常系）。"""
    # 準備
    repo = git_repo(
        {"a.md": "a\n", "b.md": "b\n", "c.md": "c\n", "d.md": "d\n", "files.yaml": ROWS_ABCD}
    )
    head = run_git(repo, "rev-parse", "HEAD").strip()
    commit_all(repo, {"files.yaml": ROWS_ABCD + f"checkpoint:\n  commit: {head}\n"})
    commit_all(repo, {"a.md": "a2\n"})
    write_files(repo, {"b.md": "b2\n"})
    # 実行
    result = find_changed(repo, "files.yaml")
    # 検証
    assert result.base.kind == BaseKind.CHECKPOINT_COMMIT
    assert result.files == ("a.md", "b.md")


def test_find_changed_when_reviewed_same_content(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """見直し済みで中身が同じファイルを除く（正常系）。"""
    # 準備
    repo = git_repo({"d.md": "d\n", "files.yaml": "files:\n  - path: d.md\n"})
    head = run_git(repo, "rev-parse", "HEAD").strip()
    digest = hashlib.sha256(b"d2\n").hexdigest()
    commit_all(
        repo,
        {
            "d.md": "d2\n",
            "files.yaml": (
                "files:\n  - path: d.md\n"
                f"checkpoint:\n  commit: {head}\n  reviewed:\n    - path: d.md\n      sha256: {digest}\n"
            ),
        },
    )
    # 実行
    result = find_changed(repo, "files.yaml")
    # 検証
    assert "d.md" not in result.files


def test_find_changed_when_renamed_and_deleted(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """改名と削除（正常系）。"""
    # 準備
    body = "".join(f"line {i}\n" for i in range(20))
    repo = git_repo(
        {"e.md": body, "g.md": "g\n", "files.yaml": "files:\n  - path: e.md\n  - path: g.md\n"}
    )
    head = run_git(repo, "rev-parse", "HEAD").strip()
    commit_all(
        repo,
        {"files.yaml": f"files:\n  - path: e.md\n  - path: g.md\ncheckpoint:\n  commit: {head}\n"},
    )
    run_git(repo, "mv", "e.md", "f.md")
    commit_all(repo, {"f.md": body + "added\n"}, delete=("g.md",))
    # 実行
    result = find_changed(repo, "files.yaml")
    # 検証
    assert result.files == ("f.md",)


def test_find_changed_when_commit_missing(
    git_repo: Callable[..., Path], commit_all: Callable[..., str]
) -> None:
    """記録した commit が無い（正常系）。"""
    # 準備
    missing = "0123456789abcdef0123456789abcdef01234567"
    repo = git_repo(
        {"a.md": "a\n", "files.yaml": f"files:\n  - path: a.md\ncheckpoint:\n  commit: {missing}\n"}
    )
    commit_all(repo, {"a.md": "a2\n"})
    # 実行
    result = find_changed(repo, "files.yaml")
    # 検証
    assert result.base.kind == BaseKind.FILES_YAML_COMMIT
    assert result.missing_commit == missing
    assert result.files == ("a.md",)


def test_find_changed_when_no_checkpoint_in_git(
    git_repo: Callable[..., Path], commit_all: Callable[..., str]
) -> None:
    """記録が無い Git の配信元（正常系）。"""
    # 準備
    repo = git_repo({"a.md": "a\n", "files.yaml": "files:\n  - path: a.md\n"})
    commit_all(repo, {"a.md": "a2\n"})
    # 実行
    result = find_changed(repo, "files.yaml")
    # 検証
    assert result.base.kind == BaseKind.FILES_YAML_COMMIT
    assert result.files == ("a.md",)


def test_find_changed_when_untracked_files_yaml(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    write_files: Callable[[Path, dict[str, str]], None],
    run_git: Callable[..., str],
) -> None:
    """Git に無視される管理用の YAML（正常系）。"""
    # 準備
    repo = git_repo({"a.md": "a\n", "b.md": "b\n", "c.md": "c\n"}, date="2026-01-01T00:00:00+00:00")
    exclude = repo / run_git(repo, "rev-parse", "--git-path", "info/exclude").strip()
    exclude.write_text("*.local.*\n", encoding="utf-8")
    write_files(
        repo, {"files.local.yaml": "files:\n  - path: a.md\n  - path: b.md\n  - path: c.md\n"}
    )
    boundary = datetime(2026, 1, 10, tzinfo=UTC).timestamp()
    os.utime(repo / "files.local.yaml", (boundary, boundary))
    commit_all(repo, {"a.md": "a2\n"}, date="2026-01-05T00:00:00+00:00")
    commit_all(repo, {"b.md": "b2\n"}, date="2026-01-15T00:00:00+00:00")
    write_files(repo, {"c.md": "c2\n"})
    # 実行
    result = find_changed(repo, "files.local.yaml")
    # 検証
    assert result.base.kind == BaseKind.FILES_YAML_MTIME
    assert result.files == ("b.md", "c.md")


def test_find_changed_when_outside_git(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """Git 管理外（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "a.md": "a\n",
            "b.md": "b\n",
            "files.yaml": "files:\n  - path: a.md\n  - path: b.md\ncheckpoint:\n  checked_at: '2026-01-10T00:00:00+00:00'\n",
        },
    )
    before = datetime(2026, 1, 5, tzinfo=UTC).timestamp()
    after = datetime(2026, 1, 15, tzinfo=UTC).timestamp()
    os.utime(tmp_path / "a.md", (before, before))
    os.utime(tmp_path / "b.md", (after, after))
    # 実行
    result = find_changed(tmp_path, "files.yaml")
    # 検証
    assert result.base.kind == BaseKind.CHECKPOINT_TIME
    assert result.files == ("b.md",)


def test_find_changed_when_files_yaml_missing(tmp_path: Path) -> None:
    """管理用の YAML が無い（異常系）。"""
    # 実行・検証
    with pytest.raises(FilesYamlNotFoundError) as exc_info:
        find_changed(tmp_path, "missing.yaml")
    assert exc_info.value.path == tmp_path / "missing.yaml"


def test_find_changed_when_root_is_subfolder(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """リポジトリの下のフォルダを配信元にする（正常系）。"""
    # 準備
    repo = git_repo(
        {"docs/a.md": "a\n", "other.md": "o\n", "docs/files.yaml": "files:\n  - path: a.md\n"}
    )
    head = run_git(repo, "rev-parse", "HEAD").strip()
    commit_all(
        repo, {"docs/files.yaml": f"files:\n  - path: a.md\ncheckpoint:\n  commit: {head}\n"}
    )
    commit_all(repo, {"docs/a.md": "a2\n", "other.md": "o2\n"})
    # 実行
    result = find_changed(repo / "docs", "files.yaml")
    # 検証
    assert result.files == ("a.md",)

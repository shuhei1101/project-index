from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from project_index.__main__ import main

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

ROWS_ABCD = "files:\n  - path: a.md\n  - path: b.md\n  - path: c.md\n  - path: d.md\n"


def _changed(root: Path, files_yaml: str = "files.yaml") -> int:
    """`project-index changed` を呼ぶ。"""
    return main(["changed", "--root", str(root), "--files-yaml", files_yaml])


def _payload(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    """標準出力の JSON を読む。"""
    return json.loads(capsys.readouterr().out)


def test_normal(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    write_files: Callable[[Path, dict[str, str]], None],
    run_git: Callable[..., str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """記録した commit の後の変更と未 commit の変更を出し、見直し済みを除く（正常系）。"""
    # 準備
    repo = git_repo(
        {"a.md": "a\n", "b.md": "b\n", "c.md": "c\n", "d.md": "d\n", "files.yaml": ROWS_ABCD}
    )
    head = run_git(repo, "rev-parse", "HEAD").strip()
    digest = hashlib.sha256(b"d2\n").hexdigest()
    write_files(
        repo,
        {
            "d.md": "d2\n",
            "files.yaml": ROWS_ABCD
            + f"checkpoint:\n  commit: {head}\n  reviewed:\n    - path: d.md\n      sha256: {digest}\n",
        },
    )
    commit_all(repo, {"d.md": "d2\n"})
    commit_all(repo, {"a.md": "a2\n"})
    write_files(repo, {"b.md": "b2\n"})
    # 実行
    code = _changed(repo)
    # 検証
    payload = _payload(capsys)
    assert code == 0
    assert payload["base"] == {"kind": "checkpoint_commit", "value": head}
    assert payload["files"] == ["a.md", "b.md"]


def test_normal_when_no_checkpoint_in_git(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """記録が無い Git の配信元は管理用の YAML の最後の commit を起点にする（正常系）。"""
    # 準備
    repo = git_repo(
        {"a.md": "a\n", "b.md": "b\n", "files.yaml": "files:\n  - path: a.md\n  - path: b.md\n"}
    )
    commit_all(repo, {"a.md": "a2\n"})
    # 実行
    code = _changed(repo)
    # 検証
    payload = _payload(capsys)
    assert code == 0
    assert payload["base"]["kind"] == "files_yaml_commit"
    assert payload["files"] == ["a.md"]


def test_normal_when_no_checkpoint_local_operation(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    write_files: Callable[[Path, dict[str, str]], None],
    run_git: Callable[..., str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Git に無視される管理用の YAML は変更日時を起点にする（正常系）。"""
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
    code = _changed(repo, "files.local.yaml")
    # 検証
    payload = _payload(capsys)
    assert code == 0
    assert payload["base"]["kind"] == "files_yaml_mtime"
    assert payload["files"] == ["b.md", "c.md"]


def test_normal_when_outside_git(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Git 管理外は記録した日時より後に変わったファイルを出す（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "a.md": "a\n",
            "b.md": "b\n",
            "files.yaml": (
                "files:\n  - path: a.md\n  - path: b.md\n"
                "checkpoint:\n  checked_at: '2026-01-10T00:00:00+00:00'\n"
            ),
        },
    )
    before = datetime(2026, 1, 5, tzinfo=UTC).timestamp()
    after = datetime(2026, 1, 15, tzinfo=UTC).timestamp()
    os.utime(tmp_path / "a.md", (before, before))
    os.utime(tmp_path / "b.md", (after, after))
    # 実行
    code = _changed(tmp_path)
    # 検証
    payload = _payload(capsys)
    assert code == 0
    assert payload["base"]["kind"] == "checkpoint_time"
    assert payload["files"] == ["b.md"]


def test_error_when_files_yaml_not_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """管理用の YAML が無いと終了コード 2 で終える（異常系）。"""
    # 実行
    code = _changed(tmp_path, "missing.yaml")
    # 検証
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "missing.yaml" in captured.err


def test_normal_when_checkpoint_commit_missing(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """記録した commit が無いと起点を切り替えて知らせる（正常系）。"""
    # 準備
    missing = "0123456789abcdef0123456789abcdef01234567"
    repo = git_repo(
        {"a.md": "a\n", "files.yaml": f"files:\n  - path: a.md\ncheckpoint:\n  commit: {missing}\n"}
    )
    commit_all(repo, {"a.md": "a2\n"})
    # 実行
    code = _changed(repo)
    # 検証
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 0
    assert payload["base"]["kind"] == "files_yaml_commit"
    assert payload["files"] == ["a.md"]
    assert missing in captured.err
    assert "切り替え" in captured.err


def test_normal_when_renamed_and_deleted(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """改名は改名先で出し、削除は出さない（正常系）。"""
    # 準備
    body = "".join(f"line {i}\n" for i in range(20))
    rows = "files:\n  - path: e.md\n  - path: g.md\n"
    repo = git_repo({"e.md": body, "g.md": "g\n", "files.yaml": rows})
    head = run_git(repo, "rev-parse", "HEAD").strip()
    commit_all(repo, {"files.yaml": rows + f"checkpoint:\n  commit: {head}\n"})
    run_git(repo, "mv", "e.md", "f.md")
    commit_all(repo, {"f.md": body.replace("line 0\n", "line zero\n")}, delete=("g.md",))
    # 実行
    code = _changed(repo)
    # 検証
    assert code == 0
    assert _payload(capsys)["files"] == ["f.md"]


def test_error_when_checkpoint_invalid(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """記録の形が違うと終了コード 2 で終える（異常系）。"""
    # 準備
    write_files(tmp_path, {"files.yaml": "files: []\ncheckpoint:\n  checked_at: x\n"})
    # 実行
    code = _changed(tmp_path)
    # 検証
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "checked_at" in captured.err

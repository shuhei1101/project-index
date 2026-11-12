# pyright: reportUnknownArgumentType=warning, reportUnknownLambdaType=warning
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.history import snapshot as snapshot_module
from project_index.features.history.snapshot import SnapshotStore

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.fixture
def archive_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """`git archive` の呼び出しを数える包みを差し込み、呼ばれた引数を返す。"""
    calls: list[list[str]] = []
    real = snapshot_module.run_git

    def counting(args: Any, **kwargs: Any) -> Any:
        calls.append(list(args))
        return real(args, **kwargs)

    monkeypatch.setattr(snapshot_module, "run_git", counting)
    return calls


def test_snapshot_store_checkout(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """commit の内容を書き出す（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    first = run_git(root, "rev-parse", "HEAD").strip()
    commit_all(root, {"a.yaml": "a: 2\n"})
    store = SnapshotStore(tmp_path / "snapshots")
    # 実行
    result = store.checkout(root, first)
    # 検証
    assert (result / "a.yaml").read_text(encoding="utf-8") == "a: 1\n"
    assert not list(result.parent.glob("*.tmp"))


def test_snapshot_store_checkout_when_cached(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    archive_calls: list[list[str]],
) -> None:
    """2 回目は git を呼ばない（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    commit = run_git(root, "rev-parse", "HEAD").strip()
    store = SnapshotStore(tmp_path / "snapshots")
    # 実行
    store.checkout(root, commit)
    store.checkout(root, commit)
    # 検証
    assert [call for call in archive_calls if call[0] == "archive"] == [
        ["archive", "--format=tar", commit]
    ]


def test_snapshot_store_checkout_when_concurrent(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    archive_calls: list[list[str]],
) -> None:
    """同時の書き出しは 1 回（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    commit = run_git(root, "rev-parse", "HEAD").strip()
    store = SnapshotStore(tmp_path / "snapshots")
    # 実行
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: store.checkout(root, commit), range(4)))
    # 検証
    assert len(set(results)) == 1
    assert len([call for call in archive_calls if call[0] == "archive"]) == 1


def test_snapshot_store_checkout_when_over_keep(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """古い書き出しを削除する（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    first = run_git(root, "rev-parse", "HEAD").strip()
    second = commit_all(root, {"a.yaml": "a: 2\n"})
    third = commit_all(root, {"a.yaml": "a: 3\n"})
    store = SnapshotStore(tmp_path / "snapshots", keep=2)
    # 実行
    first_dir = store.checkout(root, first)
    time.sleep(0.05)
    second_dir = store.checkout(root, second)
    time.sleep(0.05)
    third_dir = store.checkout(root, third)
    # 検証
    assert not first_dir.exists()
    assert second_dir.exists()
    assert third_dir.exists()

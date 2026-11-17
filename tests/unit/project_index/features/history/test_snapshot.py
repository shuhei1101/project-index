from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.history import snapshot as snapshot_module
from project_index.features.history.snapshot import SnapshotStore
from project_index.shared.background import BackgroundGate

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


@pytest.fixture
def archive_timeouts(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """`git archive` に指定した `timeout` を記録する包みを差し込み、記録した値を返却する。"""
    timeouts: list[object] = []
    real = snapshot_module.run_git

    def recording(args: Any, **kwargs: Any) -> Any:
        # git archive の呼び出しだけ、指定した timeout（指定が無ければ None）を記録する
        if list(args)[:1] == ["archive"]:
            timeouts.append(kwargs.get("timeout"))
        return real(args, **kwargs)

    monkeypatch.setattr(snapshot_module, "run_git", recording)
    return timeouts


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
    archive_timeouts: list[object],
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
    assert archive_timeouts == [20]


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

        def checkout(_: int) -> Path:
            return store.checkout(root, commit)

        results = list(executor.map(checkout, range(4)))
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


def _timing_out_archive(monkeypatch: pytest.MonkeyPatch, commits: set[str]) -> None:
    """`commits` の `git archive` だけ、待ち時間の上限を超えたときと同じ失敗を送る包みに差し替える。"""
    from project_index.integrations.git import GitError

    real = snapshot_module.run_git

    def timing_out(args: Any, **kwargs: Any) -> Any:
        values = list(args)
        if values[:1] == ["archive"] and values[-1] in commits:
            raise GitError(values, -1, "20 秒を超えたため止めました", timed_out=True)
        return real(args, **kwargs)

    monkeypatch.setattr(snapshot_module, "run_git", timing_out)


def test_snapshot_store_checkout_when_timed_out(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """待ち時間の上限を超えたら止めた処理と理由を送る（異常系）。"""
    from project_index.integrations.git import GIT_ARCHIVE_TIMEOUT_SEC
    from project_index.shared.errors import RevisionExportTimeoutError

    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    commit = run_git(root, "rev-parse", "HEAD").strip()
    _timing_out_archive(monkeypatch, {commit})
    store = SnapshotStore(tmp_path / "snapshots")
    # 実行・検証
    with pytest.raises(RevisionExportTimeoutError, match=commit) as caught:
        store.checkout(root, commit)
    assert caught.value.operation == "revision_export"
    assert caught.value.commit == commit
    assert caught.value.limit_sec == GIT_ARCHIVE_TIMEOUT_SEC
    assert not list((tmp_path / "snapshots").glob(f"*/{commit}"))
    assert not list((tmp_path / "snapshots").glob(f"*/{commit}.tmp"))


def test_snapshot_store_checkout_later(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """裏で書き出す（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    commit = run_git(root, "rev-parse", "HEAD").strip()
    store = SnapshotStore(tmp_path / "snapshots")
    gate = threading.Event()
    original = store.checkout

    def gated_checkout(repo_root: Path, target: str) -> Path:
        gate.wait(10)
        return original(repo_root, target)

    monkeypatch.setattr(store, "checkout", gated_checkout)
    # 実行
    thread = store.checkout_later([(root, commit)])
    exporting_before = store.exporting
    exported_before = list((tmp_path / "snapshots").glob(f"*/{commit}"))
    gate.set()
    thread.join(timeout=30)
    # 検証
    assert exporting_before is True
    assert exported_before == []
    assert len(list((tmp_path / "snapshots").glob(f"*/{commit}"))) == 1
    assert store.exporting is False


def test_snapshot_store_checkout_later_when_timed_out(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """上限で止まった書き出しを飛ばして次へ進む（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    first = run_git(root, "rev-parse", "HEAD").strip()
    second = commit_all(root, {"a.yaml": "a: 2\n"})
    _timing_out_archive(monkeypatch, {first})
    store = SnapshotStore(tmp_path / "snapshots")
    # 実行
    with caplog.at_level(logging.WARNING, logger=snapshot_module.__name__):
        thread = store.checkout_later([(root, first), (root, second)])
        thread.join(timeout=30)
    # 検証
    assert list((tmp_path / "snapshots").glob(f"*/{first}")) == []
    assert len(list((tmp_path / "snapshots").glob(f"*/{second}"))) == 1
    assert len([record for record in caplog.records if record.levelno == logging.WARNING]) == 1
    assert store.exporting is False


def test_snapshot_store_checkout_later_when_foreground(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """要求の応答中は commit ごとに休む（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    first = run_git(root, "rev-parse", "HEAD").strip()
    second = commit_all(root, {"a.yaml": "a: 2\n"})
    slept: list[float] = []
    gate = BackgroundGate(sleep=slept.append)
    store = SnapshotStore(tmp_path / "snapshots", gate=gate)
    # 実行
    with gate.foreground():
        thread = store.checkout_later([(root, first), (root, second)])
        thread.join(timeout=30)
    # 検証
    assert len(list((tmp_path / "snapshots").glob(f"*/{first}"))) == 1
    assert len(list((tmp_path / "snapshots").glob(f"*/{second}"))) == 1
    assert len(slept) == 2

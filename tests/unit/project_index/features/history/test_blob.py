from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from project_index.features.history.blob import BlobReader

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _blob(run_git: Callable[..., str], root: Path, path: str) -> str:
    """HEAD のファイルの blob の SHA を返す。"""
    return run_git(root, "rev-parse", f"HEAD:{path}").strip()


def test_blob_reader_read_bytes(git_repo: Callable[..., Path], run_git: Callable[..., str]) -> None:
    """blob の内容を返す（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n", "b.md": "# B\n"})
    reader = BlobReader(root)
    # 実行
    first = reader.read_bytes(_blob(run_git, root, "a.yaml"))
    second = reader.read_bytes(_blob(run_git, root, "b.md"))
    reader.close()
    # 検証
    assert first == b"a: 1\n"
    assert second == b"# B\n"


def test_blob_reader_read_bytes_when_missing(
    git_repo: Callable[..., Path], run_git: Callable[..., str]
) -> None:
    """無い SHA（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    reader = BlobReader(root)
    # 実行
    missing = reader.read_bytes("0" * 40)
    found = reader.read_bytes(_blob(run_git, root, "a.yaml"))
    reader.close()
    # 検証
    assert missing is None
    assert found == b"a: 1\n"


def test_blob_reader_read_bytes_when_process_exited(
    git_repo: Callable[..., Path], run_git: Callable[..., str]
) -> None:
    """終わった子プロセスを起動し直す（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    blob = _blob(run_git, root, "a.yaml")
    reader = BlobReader(root)
    reader.read_bytes(blob)
    process = reader._process  # noqa: SLF001
    assert process is not None
    process.kill()
    process.wait(timeout=5)
    # 実行
    result = reader.read_bytes(blob)
    reader.close()
    # 検証
    assert result == b"a: 1\n"


def test_blob_reader_read_bytes_when_concurrent(
    git_repo: Callable[..., Path], run_git: Callable[..., str]
) -> None:
    """並行の読み取りで内容を取り違えない（正常系）。"""
    # 準備
    files = {f"f{number:02d}.txt": f"content {number}\n" for number in range(20)}
    root = git_repo(files)
    expected = {_blob(run_git, root, name): content.encode() for name, content in files.items()}
    reader = BlobReader(root)
    results: list[tuple[str, bytes | None]] = []
    lock = threading.Lock()

    def work() -> None:
        for _ in range(5):
            for blob in expected:
                data = reader.read_bytes(blob)
                with lock:
                    results.append((blob, data))

    threads = [threading.Thread(target=work) for _ in range(4)]
    # 実行
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    reader.close()
    # 検証
    assert len(results) == 400
    assert all(data == expected[blob] for blob, data in results)


def test_blob_reader_read_text_when_not_utf8(
    git_repo: Callable[..., Path], run_git: Callable[..., str]
) -> None:
    """UTF-8 で読めない内容（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    (root / "x.txt").write_bytes("日本".encode("shift_jis"))
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "sjis")
    reader = BlobReader(root)
    # 実行
    result = reader.read_text(_blob(run_git, root, "x.txt"))
    reader.close()
    # 検証
    assert result is None

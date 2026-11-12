from __future__ import annotations

import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from project_index.features.lifecycle.control import RestartControl
from project_index.features.lifecycle.types import COMMAND_TIMEOUT_SEC
from project_index.features.lifecycle.update import _run, update_clone
from project_index.shared.errors import RestartInProgressError, UpdateFailedError

if TYPE_CHECKING:
    from pathlib import Path

type Response = tuple[int, str, str] | BaseException


def _ok(stdout: str = "") -> Response:
    """終了コード 0 の応答を作る。"""
    return (0, stdout, "")


class FakeRun:
    """呼ばれたコマンドを記録し、決めた応答を順に返す `subprocess.run` の偽物。"""

    def __init__(self, *responses: Response) -> None:
        self.responses = list(responses)
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        self.kwargs.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return subprocess.CompletedProcess(argv, response[0], response[1], response[2])


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """`pyproject.toml` の `version` が `0.3.0` のクローンを返す。"""
    root = tmp_path / "clone"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "project-index"\nversion = "0.3.0"\n', encoding="utf-8"
    )
    return root


@pytest.fixture
def control() -> RestartControl:
    """uvicorn のサーバーのスタブを取り付けた再起動の制御を返す。"""
    result = RestartControl()
    result.attach(cast("Any", SimpleNamespace(should_exit=False)))
    return result


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeRun) -> None:
    """更新が呼ぶ `subprocess.run` を偽物に差し替える。"""
    monkeypatch.setattr("project_index.features.lifecycle.update.subprocess.run", fake)


def test_update_clone(
    monkeypatch: pytest.MonkeyPatch, clone: Path, control: RestartControl
) -> None:
    """取り込んで移し替えが要らなければ再起動を要求する（正常系）。"""
    # 準備
    fake = FakeRun(_ok("aaa\n"), _ok(), _ok("bbb\n"), _ok(), _ok(""))
    _install(monkeypatch, fake)
    # 実行
    result = update_clone(clone, control=control)
    # 検証
    assert result.version == "0.3.0"
    assert result.updated is True
    assert result.migration_needed is False
    assert result.restarting is True
    assert control.requested is True
    assert fake.calls[:4] == [
        ["git", "rev-parse", "HEAD"],
        ["git", "pull", "--ff-only"],
        ["git", "rev-parse", "HEAD"],
        ["uv", "sync"],
    ]
    assert fake.calls[4][0] == str(clone / ".venv" / "bin" / "python")
    assert fake.calls[4][1:] == ["-m", "project_index", "migrate", "--plan"]
    assert {call["cwd"] for call in fake.kwargs} == {clone}


def test_update_clone_when_up_to_date(
    monkeypatch: pytest.MonkeyPatch, clone: Path, control: RestartControl
) -> None:
    """新しい commit が無ければ何もしない（正常系）。"""
    # 準備
    fake = FakeRun(_ok("aaa\n"), _ok(), _ok("aaa\n"))
    _install(monkeypatch, fake)
    # 実行
    result = update_clone(clone, control=control)
    # 検証
    assert result.updated is False
    assert result.restarting is False
    assert result.version == result.previous_version
    assert ["uv", "sync"] not in fake.calls
    assert control.requested is False


def test_update_clone_when_migration_needed(
    monkeypatch: pytest.MonkeyPatch, clone: Path, control: RestartControl
) -> None:
    """移し替えが要れば再起動しない（正常系）。"""
    # 準備
    fake = FakeRun(_ok("aaa\n"), _ok(), _ok("bbb\n"), _ok(), _ok("2: rename a to b\n"))
    _install(monkeypatch, fake)
    # 実行
    result = update_clone(clone, control=control)
    # 検証
    assert result.migration_needed is True
    assert result.restarting is False
    assert control.requested is False


def test_update_clone_when_in_progress(
    monkeypatch: pytest.MonkeyPatch, clone: Path, control: RestartControl
) -> None:
    """再起動を要求済みなら断る（異常系）。"""
    # 準備
    fake = FakeRun()
    _install(monkeypatch, fake)
    control.request()
    # 実行・検証
    with pytest.raises(RestartInProgressError):
        update_clone(clone, control=control)
    assert fake.calls == []


def test_update_clone_when_up_to_date_then_again(
    monkeypatch: pytest.MonkeyPatch, clone: Path, control: RestartControl
) -> None:
    """新しい commit が無くて返した後にもう一度呼べる（正常系）。"""
    # 準備
    fake = FakeRun(_ok("aaa\n"), _ok(), _ok("aaa\n"), _ok("aaa\n"), _ok(), _ok("aaa\n"))
    _install(monkeypatch, fake)
    update_clone(clone, control=control)
    # 実行
    result = update_clone(clone, control=control)
    # 検証
    assert result.updated is False


def test_update_clone_when_failed_then_again(
    monkeypatch: pytest.MonkeyPatch, clone: Path, control: RestartControl
) -> None:
    """取り込みに失敗した後にもう一度呼べる（異常系）。"""
    # 準備
    fake = FakeRun(
        _ok("aaa\n"),
        (1, "", "Not possible to fast-forward"),
        _ok("aaa\n"),
        _ok(),
        _ok("aaa\n"),
    )
    _install(monkeypatch, fake)
    with pytest.raises(UpdateFailedError):
        update_clone(clone, control=control)
    # 実行
    result = update_clone(clone, control=control)
    # 検証
    assert result.updated is False


def test_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """標準出力を返す（正常系）。"""
    # 準備
    fake = FakeRun(_ok("abc"))
    _install(monkeypatch, fake)
    # 実行
    result = _run(["git", "status"], cwd=tmp_path)
    # 検証
    assert result == "abc"
    assert fake.kwargs[0]["timeout"] == COMMAND_TIMEOUT_SEC


def test_run_when_failed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """終了コードが 0 以外（異常系）。"""
    # 準備
    fake = FakeRun((1, "", "Not possible to fast-forward"))
    _install(monkeypatch, fake)
    # 実行・検証
    with pytest.raises(UpdateFailedError) as exc_info:
        _run(["git", "pull", "--ff-only"], cwd=tmp_path)
    assert exc_info.value.command == ["git", "pull", "--ff-only"]
    assert exc_info.value.stderr == "Not possible to fast-forward"


def test_run_when_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """打ち切る（異常系）。"""
    # 準備
    fake = FakeRun(subprocess.TimeoutExpired(["uv", "sync"], COMMAND_TIMEOUT_SEC))
    _install(monkeypatch, fake)
    # 実行・検証
    with pytest.raises(UpdateFailedError):
        _run(["uv", "sync"], cwd=tmp_path)


def test_run_when_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """コマンドが無い（異常系）。"""
    # 準備
    fake = FakeRun(FileNotFoundError("uv"))
    _install(monkeypatch, fake)
    # 実行・検証
    with pytest.raises(UpdateFailedError):
        _run(["uv", "sync"], cwd=tmp_path)

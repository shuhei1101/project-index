from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, cast

import pytest

from project_index.features.lifecycle.control import RestartControl
from project_index.shared.errors import RestartInProgressError


def _stub_server() -> Any:
    """`should_exit` だけを持つ uvicorn のサーバーのスタブを作る。"""
    return cast("Any", SimpleNamespace(should_exit=False))


def test_attach() -> None:
    """取り付けたサーバーに停止を伝える（正常系）。"""
    # 準備
    control = RestartControl()
    server = _stub_server()
    control.attach(server)
    # 実行
    control.request()
    # 検証
    assert server.should_exit is True


def test_request() -> None:
    """停止を伝えて結果を返す（正常系）。"""
    # 準備
    control = RestartControl()
    control.attach(_stub_server())
    # 実行
    result = control.request()
    # 検証
    assert result.pid == os.getpid()
    assert result.restarting is True
    assert control.requested is True


def test_request_when_in_progress() -> None:
    """2 回目の要求を断る（異常系）。"""
    # 準備
    control = RestartControl()
    control.attach(_stub_server())
    control.request()
    # 実行・検証
    with pytest.raises(RestartInProgressError):
        control.request()

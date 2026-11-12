from __future__ import annotations

import argparse
import io
import sys
from typing import TYPE_CHECKING

from project_index.features.prompt_doc.cli import run_prompt_doc

if TYPE_CHECKING:
    import pytest


def test_run_prompt_doc(
    session_context_yaml: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """変換した Markdown を出す（正常系）。"""
    # 準備
    monkeypatch.setattr(sys, "stdin", io.StringIO(session_context_yaml))
    # 実行
    code = run_prompt_doc(argparse.Namespace())
    # 検証
    out, err = capsys.readouterr()
    assert code == 0
    assert out.startswith("# SessionStart の配信元の一覧")
    assert err == ""


def test_run_prompt_doc_when_invalid(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """変換できない YAML（異常系）。"""
    # 準備
    monkeypatch.setattr(sys, "stdin", io.StringIO("name: ["))
    # 実行
    code = run_prompt_doc(argparse.Namespace())
    # 検証
    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert "YAML を読み込めません" in err

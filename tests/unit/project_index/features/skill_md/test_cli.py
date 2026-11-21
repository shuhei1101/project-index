from __future__ import annotations

import argparse
import io
import json
import sys
from typing import TYPE_CHECKING, Any

from project_index.features.skill_md.cli import run_skill_md

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest


def test_run_skill_md(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """書き換えたパスを出す（正常系）。"""
    # 準備
    root = write_source(tmp_path)
    write_flow(root, "a", skill_flow("a"))
    monkeypatch.chdir(root)
    # 実行
    code = run_skill_md(argparse.Namespace(check=False, paths=[]))
    # 検証
    out, err = capsys.readouterr()
    assert code == 0
    assert out == "skills/a/SKILL.md\n"
    assert err == ""


def test_run_skill_md_when_invalid(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """組み立てられない（異常系）。"""
    # 準備
    root = write_source(tmp_path / "sample")
    write_flow(root, "a", skill_flow("a", skill={"path": "../outside/SKILL.md"}))
    monkeypatch.chdir(root)
    # 実行
    code = run_skill_md(argparse.Namespace(check=False, paths=[]))
    # 検証
    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert "docs/agent-flow/a.yaml" in err
    assert "skill.path" in err


def test_run_skill_md_when_check(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """検査のモードは違反があっても 0（正常系）。"""
    # 準備
    root = write_source(tmp_path / "sample")
    write_flow(root, "a", skill_flow("a"))
    monkeypatch.chdir(root)
    text = json.dumps(skill_flow("a", skill={"path": "../outside/SKILL.md"}))
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    # 実行
    code = run_skill_md(argparse.Namespace(check=True, paths=[]))
    # 検証
    out, _ = capsys.readouterr()
    assert code == 0
    violations = json.loads(out)
    assert [violation["path"] for violation in violations] == ["skill.path"]
    assert set(violations[0]) == {"path", "rule", "fix"}

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from project_index.main import run_migrate, run_serve

from project_index import main as main_module
from project_index.__main__ import build_parser, main

PYPROJECT_PATH = Path(__file__).parents[3] / "pyproject.toml"


def test_build_parser() -> None:
    """コマンド名が project-index になる（正常系）。"""
    # 実行
    parser = build_parser()
    # 検証
    assert parser.prog == "project-index"


def test_build_parser_when_serve() -> None:
    """serve の処理を引く（正常系）。"""
    # 準備
    parser = build_parser()
    # 実行
    args = parser.parse_args(["serve"])
    # 検証
    assert args.cmd == "serve"
    assert args.handler is run_serve


def test_build_parser_when_migrate() -> None:
    """migrate の引数と処理を引く（正常系）。"""
    # 準備
    parser = build_parser()
    # 実行
    args = parser.parse_args(["migrate", "--plan", "--source", "/tmp/a/project-index.yaml"])
    # 検証
    assert args.cmd == "migrate"
    assert args.plan is True
    assert args.record is False
    assert args.allow_destructive is False
    assert args.source == "/tmp/a/project-index.yaml"
    assert args.handler is run_migrate


def test_build_parser_when_files() -> None:
    """files の引数と処理を引く（正常系）。"""
    # 準備
    parser = build_parser()
    # 実行
    args = parser.parse_args(
        ["files", "--root", "/tmp/a", "--paths", "src/**", "--paths", "docs/**"]
    )
    # 検証
    assert args.cmd == "files"
    assert args.root == "/tmp/a"
    assert args.paths == ["src/**", "docs/**"]
    assert args.exclude == []
    assert args.handler is main_module.run_files


def test_build_parser_when_prompt_doc() -> None:
    """prompt-doc の処理を引く（正常系）。"""
    # 準備
    from project_index.features.prompt_doc.cli import run_prompt_doc

    parser = build_parser()
    # 実行
    args = parser.parse_args(["prompt-doc"])
    # 検証
    assert args.cmd == "prompt-doc"
    assert args.handler is run_prompt_doc


def test_build_parser_when_plan_and_record() -> None:
    """--plan と --record は同時に渡せない（異常系）。"""
    # 準備
    parser = build_parser()
    # 実行・検証
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["migrate", "--plan", "--record"])
    assert exc_info.value.code == 2


def test_main_when_version(capsys: pytest.CaptureFixture[str]) -> None:
    """バージョンを出す（正常系）。"""
    # 準備
    with PYPROJECT_PATH.open("rb") as f:
        expected_version = tomllib.load(f)["project"]["version"]
    # 実行
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    # 検証
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"project-index {expected_version}\n"


def test_main_when_help(capsys: pytest.CaptureFixture[str]) -> None:
    """使い方を出す（正常系）。"""
    # 実行
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    # 検証
    assert exc_info.value.code == 0
    assert capsys.readouterr().out.startswith("usage: project-index")


def test_main_when_no_command(capsys: pytest.CaptureFixture[str]) -> None:
    """サブコマンドが無い（異常系）。"""
    # 実行
    with pytest.raises(SystemExit) as exc_info:
        main([])
    # 検証
    assert exc_info.value.code == 2
    assert "cmd" in capsys.readouterr().err

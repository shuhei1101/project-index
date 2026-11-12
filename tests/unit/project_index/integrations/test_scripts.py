from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from project_index.integrations.scripts import (
    ScriptFailedError,
    ScriptNotFoundError,
    ScriptTimeoutError,
    check_runnable,
    run_script,
)


def test_run_script(tmp_path: Path) -> None:
    """標準入力を受けて標準出力を返す（正常系）。"""
    # 準備
    run = [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"]
    # 実行
    result = run_script(run, cwd=tmp_path, stdin="abc", timeout_sec=10)
    # 検証
    assert result.stdout == "ABC\n"


def test_run_script_when_cwd(tmp_path: Path) -> None:
    """配信元の直下で動かす（正常系）。"""
    # 準備
    run = [sys.executable, "-c", "import os; print(os.getcwd())"]
    # 実行
    result = run_script(run, cwd=tmp_path, timeout_sec=10)
    # 検証
    assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()


def test_run_script_when_timeout(tmp_path: Path) -> None:
    """制限時間を超える（異常系）。"""
    # 準備
    code = (
        "import os, pathlib, time; pathlib.Path('pid').write_text(str(os.getpid())); time.sleep(10)"
    )
    run = [sys.executable, "-c", code]
    # 実行・検証
    with pytest.raises(ScriptTimeoutError):
        run_script(run, cwd=tmp_path, timeout_sec=1.0)
    pid = int((tmp_path / "pid").read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_run_script_when_failed(tmp_path: Path) -> None:
    """終了コードが 0 以外（異常系）。"""
    # 準備
    code = (
        "import sys\nfor i in range(1, 11):\n    print(f'line{i}', file=sys.stderr)\nsys.exit(1)\n"
    )
    run = [sys.executable, "-c", code]
    # 実行・検証
    with pytest.raises(ScriptFailedError) as exc_info:
        run_script(run, cwd=tmp_path, timeout_sec=10)
    assert exc_info.value.exit_code == 1
    assert "line6" in exc_info.value.reason
    assert "line10" in exc_info.value.reason
    assert "line5" not in exc_info.value.reason


def test_check_runnable(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """PATH のコマンドとあるスクリプト（正常系）。"""
    # 準備
    write_files(tmp_path, {"scripts/a.py": "print('a')\n"})
    # 実行
    result = check_runnable(["python3", "scripts/a.py"], cwd=tmp_path)
    # 検証
    assert Path(result[0]).is_absolute()
    assert Path(result[0]).name == "python3"


def test_check_runnable_when_server_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PATH に無いコマンドをサーバーの Python の環境から引く（正常系）。"""
    # 準備
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    bin_dir = tmp_path / "env" / "bin"
    bin_dir.mkdir(parents=True)
    command = bin_dir / "project-index"
    command.write_text("#!/bin/sh\n", encoding="utf-8")
    command.chmod(0o755)
    monkeypatch.setenv("PATH", str(empty_dir))
    monkeypatch.setattr(sys, "executable", str(bin_dir / "python"))
    # 実行
    result = check_runnable(["project-index", "prompt-doc"], cwd=tmp_path)
    # 検証
    assert result == [str(command), "prompt-doc"]


def test_check_runnable_when_empty(tmp_path: Path) -> None:
    """コマンドが空（異常系）。"""
    # 実行・検証
    with pytest.raises(ScriptNotFoundError):
        check_runnable([], cwd=tmp_path)


def test_check_runnable_when_command_missing(tmp_path: Path) -> None:
    """コマンドが無い（異常系）。"""
    # 実行・検証
    with pytest.raises(ScriptNotFoundError):
        check_runnable(["no-such-command-xyz"], cwd=tmp_path)


def test_check_runnable_when_script_missing(tmp_path: Path) -> None:
    """スクリプトのファイルが無い（異常系）。"""
    # 実行・検証
    with pytest.raises(ScriptNotFoundError) as exc_info:
        check_runnable(["python3", "scripts/none.py"], cwd=tmp_path)
    assert "scripts/none.py" in exc_info.value.reason


def test_run_script_when_at(git_repo: Callable[..., Path], run_git: Callable[..., str]) -> None:
    """default_ref のスクリプトを動かす（正常系）。"""
    # 準備
    repo = git_repo({"scripts/a.py": 'print("develop")\n'})
    commit = run_git(repo, "rev-parse", "HEAD").strip()
    (repo / "scripts/a.py").write_text('print("disk")\n', encoding="utf-8")
    # 実行
    result = run_script(
        [sys.executable, "scripts/a.py"], cwd=repo, timeout_sec=10, at=(repo, commit)
    )
    # 検証
    assert result.stdout == "develop\n"

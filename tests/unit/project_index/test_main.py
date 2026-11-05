"""project-index コマンドの入口の単体テスト。"""

import pytest

from project_index.__main__ import main


def test_main(capsys: pytest.CaptureFixture[str]) -> None:
    """引数が無いときは使い方を出す（正常系）。"""
    # 準備
    argv: list[str] = []
    # 実行
    result = main(argv)
    # 検証
    assert result == 0
    assert capsys.readouterr().out.startswith("usage: project-index")


def test_main_when_version(capsys: pytest.CaptureFixture[str]) -> None:
    """`--version` でバージョンを出す（正常系）。"""
    # 準備
    argv = ["--version"]
    # 実行・検証
    with pytest.raises(SystemExit) as exc_info:
        main(argv)
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == "project-index 0.0.0\n"


def test_main_when_unknown_argument(capsys: pytest.CaptureFixture[str]) -> None:
    """知らない引数で使い方の誤りにする（異常系）。"""
    # 準備
    argv = ["--unknown"]
    # 実行・検証
    with pytest.raises(SystemExit) as exc_info:
        main(argv)
    assert exc_info.value.code == 2
    assert "unrecognized arguments: --unknown" in capsys.readouterr().err

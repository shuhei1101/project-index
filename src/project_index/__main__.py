"""project-index コマンドの入口。"""

import argparse
import sys
from importlib.metadata import version

PROG = "project-index"
DIST_NAME = "project-index"


def main(argv: list[str] | None = None) -> int:
    """project-index コマンドの引数を解釈し、終了コードを返却する。"""
    parser = argparse.ArgumentParser(prog=PROG)
    # バージョンはインストールしたパッケージのメタデータを参照する
    parser.add_argument("--version", action="version", version=f"{PROG} {version(DIST_NAME)}")
    # --version と知らない引数は、解釈の中で SystemExit になる
    parser.parse_args(argv)
    # 引数が無い: 使い方を出して正常に終わる
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

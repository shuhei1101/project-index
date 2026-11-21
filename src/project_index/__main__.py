"""project-index コマンドの入口。"""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import version
from typing import TYPE_CHECKING

from project_index import DIST_NAME
from project_index.features.prompt_doc.cli import run_prompt_doc
from project_index.features.skill_md.cli import run_skill_md
from project_index.main import (
    run_changed,
    run_checkpoint,
    run_files,
    run_links,
    run_migrate,
    run_outline,
    run_serve,
    run_skew,
)

if TYPE_CHECKING:
    from collections.abc import Callable

PROG = "project-index"


def build_parser() -> argparse.ArgumentParser:
    """`--version` とサブコマンドの登録先を持つ引数の解析器を作る。"""
    parser = argparse.ArgumentParser(prog=PROG)
    # バージョンは配布のメタデータから引く（配布が入っていなければ PackageNotFoundError を伝える）
    parser.add_argument("--version", action="version", version=f"{PROG} {version(DIST_NAME)}")
    # 各サブコマンドは handler を既定値に持つ
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    serve = subparsers.add_parser("serve", help="索引のサーバーを起動する")
    serve.set_defaults(handler=run_serve)
    migrate = subparsers.add_parser("migrate", help="設定のバージョンを今のバージョンに移し替える")
    # --plan は書き換えず手順だけを出し、--record は手順を当てずにバージョンだけを書き換える
    mode = migrate.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="適用する手順を出して終わる")
    mode.add_argument("--record", action="store_true", help="version だけを今のバージョンにする")
    migrate.add_argument(
        "--source", default=None, help="移し替える配信元の project-index.yaml（省くと端末の設定）"
    )
    migrate.add_argument(
        "--allow-destructive", action="store_true", help="キーの削除など値を捨てる手順も適用する"
    )
    migrate.set_defaults(handler=run_migrate)
    files = subparsers.add_parser("files", help="管理用の YAML に記載するファイルの一覧を出す")
    files.add_argument("--root", required=True, help="配信元のフォルダ")
    files.add_argument(
        "--paths", required=True, action="append", help="範囲の glob（--root からの相対）"
    )
    files.add_argument("--exclude", action="append", default=[], help="除外するファイル名の glob")
    files.add_argument(
        "--exclude-path",
        action="append",
        default=[],
        help="除外するパスの glob（--root からの相対。documents[].paths と同じ書き方）",
    )
    files.set_defaults(handler=run_files)
    outline = subparsers.add_parser(
        "outline", help="範囲のファイルごとのアウトラインと次の段階へ進むかを 1 行の JSON で出す"
    )
    outline.add_argument("--root", required=True, help="配信元のフォルダ")
    outline.add_argument(
        "--paths",
        required=True,
        action="append",
        help="範囲の glob かファイルのパス（--root からの相対）",
    )
    outline.add_argument("--exclude", action="append", default=[], help="除外するファイル名の glob")
    outline.set_defaults(handler=run_outline)
    changed = subparsers.add_parser(
        "changed", help="確認の時点の後に中身が変わった管理用の YAML の行のファイルを出す"
    )
    changed.add_argument("--root", required=True, help="配信元のフォルダ")
    changed.add_argument(
        "--files-yaml", required=True, help="管理用の YAML のパス（--root からの相対）"
    )
    changed.set_defaults(handler=run_changed)
    checkpoint = subparsers.add_parser(
        "checkpoint", help="管理用の YAML の checkpoint に確認の時点を記録する"
    )
    checkpoint.add_argument("--root", required=True, help="配信元のフォルダ")
    checkpoint.add_argument(
        "--files-yaml", required=True, help="管理用の YAML のパス（--root からの相対）"
    )
    checkpoint.add_argument(
        "--reviewed",
        action="append",
        default=[],
        help="見直したファイルのうち commit していない変更を持つファイルのパス",
    )
    checkpoint.set_defaults(handler=run_checkpoint)
    links = subparsers.add_parser(
        "links", help="範囲の Markdown と YAML ごとに本文が指すファイルを 1 行の JSON で出す"
    )
    links.add_argument("--root", required=True, help="配信元のフォルダ")
    links.add_argument(
        "--paths",
        required=True,
        action="append",
        help="範囲の glob かファイルのパス（--root からの相対）",
    )
    links.add_argument("--exclude", action="append", default=[], help="除外するファイル名の glob")
    links.set_defaults(handler=run_links)
    skew = subparsers.add_parser(
        "skew", help="ほぼ同じ description の組・1 件だけのタグ・半数以上に付くタグを JSON で出す"
    )
    skew.add_argument("--root", required=True, help="配信元のフォルダ")
    skew.add_argument(
        "--files-yaml",
        required=True,
        action="append",
        help="管理用の YAML のパス（--root からの相対か絶対パス）",
    )
    skew.add_argument("--draft", default=None, help="まだ記載していない行の案の JSON Lines のパス")
    skew.add_argument("--only-draft", action="store_true", help="行の案の行を含む組だけを比べる")
    skew.set_defaults(handler=run_skew)
    prompt_doc = subparsers.add_parser(
        "prompt-doc", help="標準入力のプロンプトの YAML を Markdown にして標準出力に出す"
    )
    prompt_doc.set_defaults(handler=run_prompt_doc)
    skill_md = subparsers.add_parser(
        "skill-md", help="type: skill のエージェントフローから SKILL.md を生成・検査する"
    )
    skill_md.add_argument(
        "--check", action="store_true", help="標準入力のエージェントフローを書き込む前に検査する"
    )
    # `generators[].run` が付与する書き込んだ文書のパス（生成の対象は絞らない）
    skill_md.add_argument("paths", nargs="*")
    skill_md.set_defaults(handler=run_skill_md)
    return parser


def main(argv: list[str] | None = None) -> int:
    """引数を解析し、選ばれたサブコマンドの処理を呼んで終了コードを返す。"""
    # --version・--help・サブコマンドの誤りは、解析の中で SystemExit になる
    args = build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.handler
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())

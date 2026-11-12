"""`project-index prompt-doc` の処理（標準入力を変換して標準出力に出し、失敗を終了コードにする）。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from project_index.features.prompt_doc.markdown import convert_prompt
from project_index.features.prompt_doc.types import PromptDocError

if TYPE_CHECKING:
    import argparse

# YAML として読めないか、変換に使うキーが無い・型が違うときの終了コード
EXIT_PROMPT_INVALID = 1


def _read_stdin() -> str:
    """標準入力を UTF-8 で全て読む。"""
    buffer = getattr(sys.stdin, "buffer", None)
    # バイト列を持つ標準入力は端末の文字コードによらず UTF-8 で読む
    if buffer is not None:
        return str(buffer.read().decode("utf-8"))
    return sys.stdin.read()


def run_prompt_doc(args: argparse.Namespace) -> int:
    """標準入力のプロンプトの YAML を Markdown にして標準出力に出す。"""
    try:
        markdown = convert_prompt(_read_stdin())
    except PromptDocError as error:
        print(error, file=sys.stderr)
        return EXIT_PROMPT_INVALID
    sys.stdout.write(markdown)
    return 0

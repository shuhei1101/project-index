"""YAML の読み込みと往復編集の読み書き。"""

from __future__ import annotations

import re
from io import StringIO
from typing import TYPE_CHECKING

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import MarkedYAMLError

if TYPE_CHECKING:
    from ruamel.yaml.main import Representer

YAML_WIDTH = 4096
YAML_INDENT = {"mapping": 2, "sequence": 4, "offset": 2}

# 値を持たないキーの行（`{キー}:` で終わる行。配列の要素の中のキーは `- ` の後ろの列）
_VALUELESS_KEY = re.compile(r"^(?P<indent> *)(?P<dash>(?:- )*)[^\s#-][^#]*?:\s*$")
# 配列の要素の行
_SEQUENCE_ITEM = re.compile(r"^(?P<indent> *)- ")


class YamlLoadError(ValueError):
    """YAML として読めないことを、ファイル・行・列・理由で表す。"""

    def __init__(
        self,
        reason: str,
        *,
        file: str | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        super().__init__(reason)
        self.file = file
        self.line = line
        self.column = column
        self.reason = reason

    def __str__(self) -> str:
        place = ":".join(str(part) for part in (self.file, self.line, self.column) if part)
        return f"{place}: {self.reason}" if place else self.reason


def _error_from(error: Exception, file: str | None, text: str) -> YamlLoadError:
    """ruamel.yaml の誤りを、1 始まりの行と列を持つ `YamlLoadError` にする。"""
    mark = getattr(error, "problem_mark", None)
    # 誤りの 1 行目だけを理由にする
    reason = (getattr(error, "problem", None) or str(error)).strip().splitlines()[0]
    context = getattr(error, "context", None)
    if context:
        reason = f"{context}: {reason}"
    if mark is None:
        return YamlLoadError(reason, file=file)
    # ストリームの終わりで見つけた誤りは、最後の行に収める
    line = min(mark.line + 1, max(len(text.splitlines()), 1))
    return YamlLoadError(reason, file=file, line=line, column=mark.column + 1)


def load_yaml(text: str, *, file: str | None = None) -> object:
    """YAML の文字列を素の値で読む。"""
    yaml = YAML(typ="safe", pure=True)
    try:
        return yaml.load(text)
    except MarkedYAMLError as error:
        raise _error_from(error, file, text) from error


def load_roundtrip(text: str, *, file: str | None = None) -> CommentedMap:
    """コメントと順序を保つ往復編集の形で YAML を読む。"""
    yaml = YAML(typ="rt", pure=True)
    # 引用符つきの文字列を、引用符の種類を持つ文字列で読む（書き出しで同じ引用符になる）
    yaml.preserve_quotes = True
    try:
        value = yaml.load(text)
    except MarkedYAMLError as error:
        raise _error_from(error, file, text) from error
    if value is None:
        return CommentedMap()
    if not isinstance(value, CommentedMap):
        msg = "最上位が辞書ではありません"
        raise YamlLoadError(msg, file=file)
    return value


def dump_roundtrip(doc: CommentedMap, *, original: str | None = None) -> str:
    """往復編集の値を、コメント・順序・字下げを保って文字列にする。"""
    yaml = YAML(typ="rt", pure=True)
    yaml.width = YAML_WIDTH
    # 元の文字列があれば配列の字下げを合わせ、無ければ既定の字下げで書き出す
    indent = YAML_INDENT if original is None else _indent_of(original)
    yaml.indent(**indent)
    yaml.preserve_quotes = True
    yaml.representer.add_representer(str, _represent_str)
    stream = StringIO()
    yaml.dump(doc, stream)
    return stream.getvalue()


def _indent_of(original: str) -> dict[str, int]:
    """元の文字列の最初の配列の `- ` の位置から、書き出しの字下げを決める。"""
    lines = original.splitlines()
    for index, line in enumerate(lines):
        key = _VALUELESS_KEY.match(line)
        if key is None:
            continue
        key_column = len(key.group("indent")) + len(key.group("dash"))
        following = next(
            (
                rest
                for rest in lines[index + 1 :]
                if rest.strip() and not rest.lstrip().startswith("#")
            ),
            None,
        )
        # 値を持たないキーの後ろに行が無ければ、配列は見つからない
        if following is None:
            break
        item = _SEQUENCE_ITEM.match(following)
        # 次の行が `- ` で始まらない（入れ子の辞書）か、キーより左にあるときは次のキーを確認する
        if item is None or len(item.group("indent")) < key_column:
            continue
        # 次の行が `- ` で始まる: その列とキーの列の差を配列の字下げにする
        offset = len(item.group("indent")) - key_column
        return {"mapping": YAML_INDENT["mapping"], "sequence": offset + 2, "offset": offset}
    # 配列が見つからないときは既定の字下げ
    return YAML_INDENT


def _represent_str(representer: Representer, data: str) -> object:
    """改行を含む引用符なしの文字列をブロックのリテラル（`|-`）で書く。"""
    if "\n" in data:
        return representer.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return representer.represent_scalar("tag:yaml.org,2002:str", data)

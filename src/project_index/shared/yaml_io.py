"""YAML の読み込みと往復編集の読み書き。"""
# pyright: reportUnknownMemberType=warning

from __future__ import annotations

from io import StringIO
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import MarkedYAMLError

YAML_WIDTH = 4096
YAML_INDENT = {"mapping": 2, "sequence": 4, "offset": 2}


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


def load_yaml(text: str, *, file: str | None = None) -> Any:  # noqa: ANN401
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


def dump_roundtrip(doc: CommentedMap) -> str:
    """往復編集の値を、コメント・順序・字下げを保って文字列にする。"""
    yaml = YAML(typ="rt", pure=True)
    yaml.width = YAML_WIDTH
    yaml.indent(**YAML_INDENT)
    yaml.preserve_quotes = True
    yaml.representer.add_representer(str, _represent_str)
    stream = StringIO()
    yaml.dump(doc, stream)
    return stream.getvalue()


def _represent_str(representer: Any, data: str) -> Any:  # noqa: ANN401
    """改行を含む引用符なしの文字列をブロックのリテラル（`|-`）で書く。"""
    if "\n" in data:
        return representer.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return representer.represent_scalar("tag:yaml.org,2002:str", data)

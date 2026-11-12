"""文書の項目のパスの読み書きと、メタデータの解決。"""
# pyright: reportUnknownArgumentType=warning, reportUnknownMemberType=warning, reportUnknownVariableType=warning

from __future__ import annotations

import re
from collections.abc import Mapping, MutableMapping, Sequence, Set
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from project_index.shared.errors import InvalidArgumentError, Violation

if TYPE_CHECKING:
    from project_index.features.documents.types import Document
    from project_index.features.sources.types import DocumentTable

METADATA_KEYS = (
    "id",
    "name",
    "description",
    "tags",
    "main_tags",
    "related",
    "status",
    "alias_type",
    "aliases",
    "command",
    "cwd",
    "url",
    "avoid",
    "skill",
    "tool",
    "path",
    "port",
    "replacement",
)

PART_PATTERN = re.compile(r"^([^.\[\]]+)((?:\[(?:\d+|[A-Za-z][A-Za-z0-9_]*)?\])*)$")
INDEX_PATTERN = re.compile(r"\[(\d+|[A-Za-z][A-Za-z0-9_]*)?\]")
PATH_EXAMPLE = "例 `a.b[0].c`・`tags[].name`・`tags[main].name`"


@dataclass(frozen=True, slots=True)
class ArraySelector:
    """項目のパスの `[]`・`[{キー}]` が表す、配列から選ぶ要素。"""

    key: str | None


Token = str | int | ArraySelector


def _invalid(path: str, message: str) -> InvalidArgumentError:
    """項目のパスの誤りを、違反 1 件の `InvalidArgumentError` にする。"""
    return InvalidArgumentError(message=message, violations=[Violation(path=path, rule=message)])


def parse_field_path(path: str) -> list[Token]:
    """ドット記法・`[n]`・`[]`・`[{キー}]` の項目のパスを、キー・位置・要素の選び方の並びにする。"""
    tokens: list[Token] = []
    for part in path.split("."):
        matched = PART_PATTERN.match(part)
        if matched is None:
            raise _invalid(path, f"項目のパス {path} の記載方法が誤っています（{PATH_EXAMPLE}）")
        tokens.append(matched.group(1))
        for inner in INDEX_PATTERN.findall(matched.group(2)):
            if not inner:
                tokens.append(ArraySelector(key=None))
            elif inner.isdecimal():
                tokens.append(int(inner))
            else:
                tokens.append(ArraySelector(key=inner))
    return tokens


def _plain_tokens(path: str, verb: str) -> list[str | int]:
    """要素の選び方を含まないパスを分ける。含めば `InvalidArgumentError` を送る。"""
    tokens = parse_field_path(path)
    if any(isinstance(token, ArraySelector) for token in tokens):
        raise _invalid(path, f"{path}: `[]`・`[{{キー}}]` を含む項目のパス{verb}")
    return [token for token in tokens if not isinstance(token, ArraySelector)]


def _select(data: Any, tokens: Sequence[Token], default: Any) -> Any:  # noqa: ANN401
    """要素の選び方を含む並びをたどり、選んだ要素ごとの値の配列にする。"""
    for depth, token in enumerate(tokens):
        if not isinstance(token, ArraySelector):
            continue
        found, current = _walk(data, tokens[:depth])  # type: ignore[arg-type]
        if not found or not isinstance(current, list):
            return default
        rest = tokens[depth + 1 :]
        values: list[Any] = []
        for element in current:
            if token.key is not None and not (
                isinstance(element, Mapping) and element.get(token.key)
            ):
                continue
            if any(isinstance(item, ArraySelector) for item in rest):
                picked = _select(element, rest, None)
                if isinstance(picked, list):
                    values.extend(picked)
                continue
            ok, value = _walk(element, rest)  # type: ignore[arg-type]
            if ok:
                values.append(value)
        return values
    found, value = _walk(data, tokens)  # type: ignore[arg-type]
    return value if found else default


def _walk(data: Any, tokens: Sequence[str | int]) -> tuple[bool, Any]:  # noqa: ANN401
    """先頭からたどり、たどれたか・たどり着いた値を返す。"""
    current = data
    for token in tokens:
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                return False, None
            current = current[token]
        else:
            if not isinstance(current, Mapping) or token not in current:
                return False, None
            current = current[token]
    return True, current


def _join(tokens: Sequence[str | int]) -> str:
    """キーと位置の並びを項目のパスの文字列に戻す。"""
    text = ""
    for token in tokens:
        if isinstance(token, int):
            text += f"[{token}]"
        else:
            text += f".{token}" if text else token
    return text


def get_field(data: Mapping[str, Any], path: str, *, default: Any = None) -> Any:  # noqa: ANN401
    """項目のパスで指した値を返す。"""
    return _select(data, parse_field_path(path), default)


def set_field(data: MutableMapping[str, Any], path: str, value: Any) -> None:  # noqa: ANN401, C901
    """項目のパスで指した場所へ値を書く。"""
    tokens = _plain_tokens(path, "には書き込めません")
    current: Any = data
    for depth, token in enumerate(tokens[:-1]):
        following = tokens[depth + 1]
        if isinstance(token, int):
            if not isinstance(current, list):
                raise _invalid(path, f"{path}: {_join(tokens[:depth])} は配列ではありません")
            if token > len(current):
                raise _invalid(
                    path, f"{path}: 位置 {token} は配列の長さ {len(current)} を超えています"
                )
            if token == len(current):
                current.append([] if isinstance(following, int) else {})
            current = current[token]
        else:
            if not isinstance(current, MutableMapping):
                raise _invalid(path, f"{path}: {_join(tokens[:depth])} は辞書ではありません")
            if token not in current:
                current[token] = [] if isinstance(following, int) else {}
            current = current[token]
    last = tokens[-1]
    if isinstance(last, int):
        if not isinstance(current, list):
            raise _invalid(path, f"{path}: {_join(tokens[:-1])} は配列ではありません")
        if last > len(current):
            raise _invalid(path, f"{path}: 位置 {last} は配列の長さ {len(current)} を超えています")
        if last == len(current):
            current.append(value)
        else:
            current[last] = value
        return
    if not isinstance(current, MutableMapping):
        raise _invalid(path, f"{path}: {_join(tokens[:-1])} は辞書ではありません")
    current[last] = value


def delete_field(data: MutableMapping[str, Any], path: str) -> bool:
    """項目のパスで指した値を削除する。"""
    tokens = _plain_tokens(path, "は削除できません")
    found, parent = _walk(data, tokens[:-1])
    if not found:
        return False
    last = tokens[-1]
    if isinstance(last, int):
        if not isinstance(parent, list) or last >= len(parent):
            return False
        del parent[last]
        return True
    if not isinstance(parent, MutableMapping) or last not in parent:
        return False
    del parent[last]
    return True


def resolve_metadata(data: Mapping[str, Any], table: DocumentTable) -> dict[str, Any]:
    """文書の行の `metadata` の列名の対応で、文書の内容から共通のキーの値を取る。"""
    result: dict[str, Any] = {}
    for key in METADATA_KEYS:
        value = get_field(data, table.metadata.get(key, key))
        if value is not None:
            result[key] = value
    if table.alias_type is not None:
        result["alias_type"] = table.alias_type
    return result


def missing_ref_fields(data: Mapping[str, Any], table: DocumentTable) -> list[tuple[str, str]]:
    """`metadata` に書いた列のうち、文書の内容に値が無い列を `(キー, 列名)` で返す。"""
    return [
        (key, column) for key, column in table.metadata.items() if get_field(data, column) is None
    ]


def unresolved_related(metadata: Mapping[str, Any], ids: Set[str]) -> list[str]:
    """`related` のうち、`to` が配信元の文書の ID の集合に無い関連の `to` を返す。"""
    rows = metadata.get("related")
    # related が配列でない: 照合する関連が無い
    if not isinstance(rows, list):
        return []
    unresolved: list[str] = []
    for row in rows:
        # 文字列の to を持たない要素は関連の行ではない（related_links と同じ読み方）
        if not isinstance(row, dict) or not isinstance(row.get("to"), str):
            continue
        # 文字列の source を持つ関連は別の配信元を指すので照合しない
        if isinstance(row.get("source"), str):
            continue
        if row["to"] not in ids:
            unresolved.append(row["to"])
    return unresolved


def is_markdown_body(document: Document) -> bool:
    """文書の本文が Markdown のファイルか（`body_path` の拡張子が `.md`）。"""
    return (
        document.body_path is not None and PurePosixPath(document.body_path).suffix.lower() == ".md"
    )

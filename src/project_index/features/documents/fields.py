"""文書の項目のパスの読み書きと、メタデータの解決。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from project_index.shared.errors import InvalidArgumentError, Violation
from project_index.shared.narrowing import is_dict, is_list

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, MutableMapping, Sequence, Set

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
    "visibility",
)

PART_PATTERN = re.compile(r"^([^.\[\]]+)((?:\[(?:\d+|[A-Za-z][A-Za-z0-9_]*)?\])*)$")
INDEX_PATTERN = re.compile(r"\[(\d+|[A-Za-z][A-Za-z0-9_]*)?\]")
PATH_EXAMPLE = "例 `a.b[0].c`・`tags[].name`・`tags[main].name`・`**.refs[]`"
ANY_DEPTH = "**"
ANY_DEPTH_PREFIX = f"{ANY_DEPTH}."


@dataclass(frozen=True, slots=True)
class ArraySelector:
    """項目のパスの `[]`・`[{キー}]` が表す、配列から選ぶ要素。"""

    key: str | None


@dataclass(frozen=True, slots=True)
class AnyDepth:
    """項目のパスの先頭の `**` が表す、文書の中のどの深さの辞書からも残りのパスをたどるマーカー。"""


Token = str | int | ArraySelector | AnyDepth


def _invalid(path: str, message: str) -> InvalidArgumentError:
    """項目のパスの誤りを、違反 1 件の `InvalidArgumentError` にする。"""
    return InvalidArgumentError(message=message, violations=[Violation(path=path, rule=message)])


def parse_field_path(path: str) -> list[Token]:
    """ドット記法・`[n]`・`[]`・`[{キー}]`・先頭の `**.` の項目のパスを、トークンの並びにする。"""
    tokens: list[Token] = []
    parts = path.split(".")
    # 先頭の `**` は、後ろに区切りがあるときだけ「どの深さでも」になる
    if parts[0] == ANY_DEPTH and len(parts) > 1:
        tokens.append(AnyDepth())
        parts = parts[1:]
    for part in parts:
        matched = PART_PATTERN.match(part)
        # `*` を含む区切りは、先頭の `**` 以外の位置には書けない
        if matched is None or "*" in matched.group(1):
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
    if any(isinstance(token, ArraySelector | AnyDepth) for token in tokens):
        raise _invalid(path, f"{path}: `**`・`[]`・`[{{キー}}]` を含む項目のパス{verb}")
    return _plain(tokens)


def _select(data: object, tokens: Sequence[Token], default: object) -> object:
    """要素の選び方を含む並びをたどり、選んだ要素ごとの値の配列にする。"""
    for depth, token in enumerate(tokens):
        if not isinstance(token, ArraySelector):
            continue
        found, current = _walk(data, _plain(tokens[:depth]))
        if not found or not is_list(current):
            return default
        return _select_elements(current, token, tokens[depth + 1 :])
    found, value = _walk(data, _plain(tokens))
    return value if found else default


def _select_elements(
    elements: list[object], token: ArraySelector, rest: Sequence[Token]
) -> list[object]:
    """配列の要素のうち選び方に当たる要素から、残りのパスの値を集める。"""
    values: list[object] = []
    for element in elements:
        # `[{キー}]` は、そのキーが真の値を持つ辞書の要素だけを選ぶ
        if token.key is not None and not (is_dict(element) and element.get(token.key)):
            continue
        # 残りのパスにも要素の選び方がある: 要素ごとに選んだ値を平らに並べる
        if any(isinstance(item, ArraySelector) for item in rest):
            picked = _select(element, rest, None)
            if is_list(picked):
                values.extend(picked)
            continue
        ok, value = _walk(element, _plain(rest))
        if ok:
            values.append(value)
    return values


def _plain(tokens: Sequence[Token]) -> list[str | int]:
    """要素の選び方を含まない並びを、キーと位置の並びとして読む。"""
    return [token for token in tokens if not isinstance(token, ArraySelector | AnyDepth)]


def _walk(data: object, tokens: Sequence[str | int]) -> tuple[bool, object]:
    """先頭からたどり、たどれたか・たどり着いた値を返す。"""
    current = data
    for token in tokens:
        if isinstance(token, int):
            if not is_list(current) or token >= len(current):
                return False, None
            current = current[token]
        else:
            if not is_dict(current) or token not in current:
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


def get_field(data: Mapping[str, Any], path: str, *, default: object = None) -> object:
    """項目のパスで指した値を返す。"""
    tokens = parse_field_path(path)
    if isinstance(tokens[0], AnyDepth):
        return _select_any_depth(data, tokens[1:], default)
    return _select(data, tokens, default)


def _dicts(data: object) -> Iterator[dict[object, object]]:
    """値とその中の全ての辞書を、文書の中の出現順（深さ優先。辞書は中の値より先）に返す。"""
    if is_dict(data):
        yield data
        for value in data.values():
            yield from _dicts(value)
    elif is_list(data):
        for value in data:
            yield from _dicts(value)


_MISSING = object()


def _select_any_depth(data: object, rest: Sequence[Token], default: object) -> object:
    """全ての辞書で残りのパスをたどり、たどれた値を出現順に並べる。"""
    spread = any(isinstance(token, ArraySelector) for token in rest)
    values: list[object] = []
    for found in _dicts(data):
        picked = _select(found, rest, _MISSING)
        if picked is _MISSING:
            continue
        # 残りのパスが要素を選ぶときは、辞書ごとの配列を平らにつなぐ
        if spread and is_list(picked):
            values.extend(picked)
        elif not spread:
            values.append(picked)
    return values or default


def field_arrays(data: Mapping[str, Any], path: str) -> list[list[object]]:
    """列名が指す配列を、文書の中の元の配列のまま出現順に返す。"""
    tokens = parse_field_path(path)
    # 末尾の `[]` は配列そのものを指すものとして扱う
    if tokens[-1] == ArraySelector(key=None):
        tokens = tokens[:-1]
    if any(isinstance(token, ArraySelector) for token in tokens):
        raise _invalid(path, f"{path}: 配列を指す列名ではありません")
    sources: list[object] = list(_dicts(data)) if isinstance(tokens[0], AnyDepth) else [data]
    rest = _plain(tokens)
    arrays: list[list[object]] = []
    for source in sources:
        found, value = _walk(source, rest)
        if found and is_list(value):
            arrays.append(value)
    return arrays


def set_field(data: MutableMapping[str, Any], path: str, value: object) -> None:
    """項目のパスで指した場所へ値を書く。"""
    _set_tokens(data, _plain_tokens(path, "には書き込めません"), value, path)


def set_field_at(
    data: MutableMapping[str, Any], tokens: Sequence[str | int], value: object
) -> None:
    """キーと位置の並びで指した場所へ値を書く（`.` を含むキーも 1 つのキー）。"""
    _set_tokens(data, tokens, value, _join(tokens))


def _set_tokens(
    data: MutableMapping[str, Any], tokens: Sequence[str | int], value: object, path: str
) -> None:
    """キーと位置の並びをたどって値を書く。違反の文には `path` を使う。"""
    current: object = data
    for depth, token in enumerate(tokens[:-1]):
        # 途中のキー・位置が無ければ、次のトークンに合わせて空の配列か辞書を作る
        empty: object = [] if isinstance(tokens[depth + 1], int) else {}
        current = _child(current, token, empty, path, tokens[:depth])
    _put(current, tokens[-1], value, path, tokens[:-1])


# 参照の型の項目のパスの先頭
REF_PATH_PREFIX = "#"


def resolve_array(
    data: MutableMapping[str, Any], schema: Mapping[str, Any], path: str, *, create: bool
) -> object | None:
    """`add_to`・`remove_from` のキーの項目のパスを、文書の中の 1 つの値へ解いて返す。"""
    # `#` で始まるパス: スキーマの `x-key` の値で要素を指し、項目を作らない
    if path.startswith(REF_PATH_PREFIX):
        tokens = resolve_ref_path(data, schema, path[len(REF_PATH_PREFIX) :])
        return _walk(data, tokens)[1]
    # `#` で始まらないパス: 要素の選び方を含めば、選んだ要素の値を集めた新規のリストになるため拒否する
    tokens = _plain_tokens(
        path, "は配列として指せません。`#` で始めて x-key の値で要素を指してください"
    )
    found, value = _walk(data, tokens)
    if found:
        return value
    # 項目が無い: 追加では空の配列を作り、削除では何もしない
    if not create:
        return None
    _set_tokens(data, tokens, [], path)
    return _walk(data, tokens)[1]


REF_PATH_EXAMPLE = (
    "例 `#functions[save].process`・`#functions[save#2].process`・`#notes[main.py の補足]`"
)
# 参照の型の項目のパスの名前（`[`・`]`・`.` を含まない）
REF_NAME_PATTERN = re.compile(r"[^.\[\]]+")
ORDER_PATTERN = re.compile(r"(.*)#(\d+)")


def resolve_ref_path(
    data: Mapping[str, Any], schema: Mapping[str, Any], path: str
) -> list[str | int]:
    """参照の型の項目のパス（`#` の後）を、文書と種類のスキーマでキーと位置の並びに解く。"""
    tokens: list[str | int] = []
    current: object = data
    node = _schema_node(schema, schema)
    for bracket, name in _split_ref_path(path):
        # 配列に対する `[...]` は、スキーマの `x-key` の値で要素を選ぶ
        if bracket is not None and is_list(current):
            position = _element_position(current, node, bracket, path, tokens)
            tokens.append(position)
            current = current[position]
            node = _schema_node(schema, node.get("items"))
            continue
        key = name if bracket is None else bracket
        if not is_dict(current) or key not in current:
            raise _invalid(path, f"{path}: {_join(tokens) or '最上位'} にキー {key} がありません")
        tokens.append(key)
        current = current[key]
        node = _schema_node(schema, _property_schema(node, key))
    return tokens


def _split_ref_path(path: str) -> list[tuple[str | None, str | None]]:
    """参照の型の項目のパスを、`[...]` の値か `.` で区切った名前の並びに分ける。

    `[...]` の中の対応の取れた `[` `]` は値の一部にする。
    要素は `(値, None)`（`[...]`）か `(None, 名前)`。
    """
    invalid = _invalid(path, f"項目のパス {path} の記載方法が誤っています（{REF_PATH_EXAMPLE}）")
    # 先頭は名前
    head = REF_NAME_PATTERN.match(path)
    if head is None:
        raise invalid
    parts: list[tuple[str | None, str | None]] = [(None, head.group())]
    position = head.end()
    while position < len(path):
        # `[...]`: 対応する `]` までを値にする
        if path[position] == "[":
            end = _closing_bracket(path, position)
            if end is None:
                raise invalid
            parts.append((path[position + 1 : end], None))
            position = end + 1
            continue
        # `.名前`: `.` の後に空でない名前が要る
        name = REF_NAME_PATTERN.match(path, position + 1) if path[position] == "." else None
        if name is None:
            # 対応する `[` の無い `]`・`]` の直後の名前・空の名前
            raise invalid
        parts.append((None, name.group()))
        position = name.end()
    return parts


def _closing_bracket(path: str, start: int) -> int | None:
    """`start` の `[` に対応する `]` の位置を返す（閉じなければ `None`）。"""
    depth = 0
    for index in range(start, len(path)):
        # `[` で 1 段深く、`]` で 1 段浅くなり、0 に戻った `]` が対応する `]`
        if path[index] == "[":
            depth += 1
        elif path[index] == "]":
            depth -= 1
            if depth == 0:
                return index
    return None


def _element_position(
    elements: list[object],
    node: Mapping[str, Any],
    value: str,
    path: str,
    parents: Sequence[str | int],
) -> int:
    """配列のスキーマの `x-key` のキーが `value` の要素の位置を返す（`{値}#{順番}` は順番目）。"""
    key = node.get("x-key")
    if not isinstance(key, str):
        raise _invalid(path, f"{path}: {_join(parents)} は x-key を持たない配列です")
    matches = _positions(elements, key, value)
    if matches:
        return matches[0]
    ordered = ORDER_PATTERN.fullmatch(value)
    if ordered is not None:
        same = _positions(elements, key, ordered.group(1))
        order = int(ordered.group(2))
        if same and 1 <= order <= len(same):
            return same[order - 1]
        if same:
            raise _invalid(path, f"{path}: {key} が {ordered.group(1)} の要素は {len(same)} 個です")
    raise _invalid(path, f"{path}: {_join(parents)} に {key} が {value} の要素がありません")


def _positions(elements: list[object], key: str, value: str) -> list[int]:
    """`key` の値を文字列にしたものが `value` の要素の位置を並べる。"""
    return [
        index
        for index, element in enumerate(elements)
        if is_dict(element) and element.get(key) is not None and str(element[key]) == value
    ]


def _property_schema(node: Mapping[str, Any], key: str) -> object:
    """辞書のスキーマから `key` の項目のスキーマを返す（無ければ `additionalProperties`）。"""
    properties = node.get("properties")
    if is_dict(properties) and key in properties:
        return properties[key]
    return node.get("additionalProperties")


def _schema_node(root: Mapping[str, Any], node: object) -> dict[str, Any]:
    """スキーマの `$ref`（`#/...`）を最上位から解き、`$ref` 以外のキーを重ねた辞書を返す。"""
    current = node
    seen: set[str] = set()
    while is_dict(current) and isinstance(current.get("$ref"), str):
        reference = str(current["$ref"])
        # 最上位の外を指す参照と、循環する参照は解かない
        if not reference.startswith("#/") or reference in seen:
            break
        seen.add(reference)
        target = _pointer(root, reference)
        rest = {key: value for key, value in current.items() if key != "$ref"}
        current = {**target, **rest} if is_dict(target) else rest
    return {str(key): value for key, value in current.items()} if is_dict(current) else {}


def _pointer(root: Mapping[str, Any], reference: str) -> object:
    """`#/a/b` の参照が指す値を返す（たどれなければ `None`）。"""
    target: object = root
    for part in reference[2:].split("/"):
        target = target.get(part) if is_dict(target) else None
    return target


def _child(
    current: object, token: str | int, empty: object, path: str, parents: Sequence[str | int]
) -> object:
    """`current` の `token` の値を返す。無ければ `empty` を置いてから返す。"""
    if isinstance(token, int):
        if not is_list(current):
            raise _invalid(path, f"{path}: {_join(parents)} は配列ではありません")
        if token > len(current):
            raise _invalid(path, f"{path}: 位置 {token} は配列の長さ {len(current)} を超えています")
        if token == len(current):
            current.append(empty)
        return current[token]
    if not is_dict(current):
        raise _invalid(path, f"{path}: {_join(parents)} は辞書ではありません")
    if token not in current:
        current[token] = empty
    return current[token]


def _put(
    current: object, last: str | int, value: object, path: str, parents: Sequence[str | int]
) -> None:
    """`current` の `last` へ値を書く（配列の末尾の次の位置は追加）。"""
    if isinstance(last, int):
        if not is_list(current):
            raise _invalid(path, f"{path}: {_join(parents)} は配列ではありません")
        if last > len(current):
            raise _invalid(path, f"{path}: 位置 {last} は配列の長さ {len(current)} を超えています")
        if last == len(current):
            current.append(value)
        else:
            current[last] = value
        return
    if not is_dict(current):
        raise _invalid(path, f"{path}: {_join(parents)} は辞書ではありません")
    current[last] = value


def delete_field(
    data: MutableMapping[str, Any], path: str, *, schema: Mapping[str, Any] | None = None
) -> bool:
    """項目のパスで指した値を削除する。"""
    # `#` で始まるパス: スキーマの `x-key` の値で要素を指す（解けなければ送る）
    if path.startswith(REF_PATH_PREFIX):
        tokens = resolve_ref_path(data, schema or {}, path[len(REF_PATH_PREFIX) :])
    else:
        # `#` で始まらないパス: 要素の選び方を含めば削除先が 1 つに決まらないため拒否する
        tokens = _plain_tokens(path, "は削除できません")
    found, parent = _walk(data, tokens[:-1])
    if not found:
        return False
    last = tokens[-1]
    if isinstance(last, int):
        if not is_list(parent) or last >= len(parent):
            return False
        del parent[last]
        return True
    if not is_dict(parent) or last not in parent:
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
    rows: object = metadata.get("related")
    # related が配列でない: 照合する関連が無い
    if not is_list(rows):
        return []
    unresolved: list[str] = []
    for row in rows:
        # 文字列の to を持たない要素は関連の行ではない（related_links と同じ読み方）
        to = row.get("to") if is_dict(row) else None
        if not is_dict(row) or not isinstance(to, str):
            continue
        # 文字列の source を持つ関連は別の配信元を指すので照合しない
        if isinstance(row.get("source"), str):
            continue
        if to not in ids:
            unresolved.append(to)
    return unresolved


def is_markdown_body(document: Document) -> bool:
    """文書の本文が Markdown のファイルか（`body_path` の拡張子が `.md`）。"""
    return (
        document.body_path is not None and PurePosixPath(document.body_path).suffix.lower() == ".md"
    )

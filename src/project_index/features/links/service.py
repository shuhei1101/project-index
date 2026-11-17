"""本文のリンクとパスの取り出しと、実在するファイルへの解決・1 行の JSON への変換。"""

from __future__ import annotations

import json
import posixpath
import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, cast

from project_index.features.documents.indexable import indexable_files, walk_files
from project_index.features.links.types import FileLinks, LinkTarget, LinkVia
from project_index.shared.yaml_io import YamlLoadError, load_yaml

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

TARGET_SUFFIXES = frozenset({".md", ".yaml", ".yml"})
YAML_SUFFIXES = frozenset({".yaml", ".yml"})
# アウトラインの MAX_READ_BYTES と同じ値（docs/pr/106/しきい値の測定/README.md）
MAX_READ_BYTES = 1_048_576
SKIP_LINK_PREFIXES = ("http:", "https:", "mailto:", "id:")
LINK_PATTERN = re.compile(r'!?\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)')
PATH_BOUNDARY_BEFORE = r"[A-Za-z0-9_\-./]"
PATH_BOUNDARY_AFTER = r"[A-Za-z0-9_\-/]"
RELATIVE_PATTERN = re.compile(r"(?<![A-Za-z0-9_\-./])(\.\.?/[^\s\"'`<>()\[\]]+)")
# trie のノードでパスの終わりを表すキー（1 文字のキーと重ならない）
_END = ""

type _Trie = dict[str, _Trie]


def links_files(
    root: Path, paths: Sequence[str], *, exclude: Sequence[str] = ()
) -> list[FileLinks]:
    """範囲の Markdown と YAML のうち、指す先を 1 件以上持つものをパスの昇順で返す。"""
    sources = [
        path
        for path in indexable_files(root, paths, exclude=exclude)
        if PurePosixPath(path).suffix.lower() in TARGET_SUFFIXES
    ]
    existing = frozenset(walk_files(root))
    path_pattern = build_path_pattern(path for path in existing if "/" in path)
    results = (file_links(root, path, existing, path_pattern) for path in sources)
    return [result for result in results if result.targets]


def file_links(
    root: Path, path: str, existing: frozenset[str], path_pattern: re.Pattern[str] | None
) -> FileLinks:
    """ファイル 1 つを読み、本文が指す実在するファイルを返す。"""
    try:
        with (root / path).open("rb") as handle:
            text = handle.read(MAX_READ_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return FileLinks(path=path, targets=())
    is_yaml = PurePosixPath(path).suffix.lower() in YAML_SUFFIXES
    texts = collect_yaml_strings(text) if is_yaml else [text]
    source_dir = posixpath.dirname(path)
    found: dict[str, LinkVia] = {}
    for value in texts:
        destinations, rest = extract_links(value)
        for destination in destinations:
            resolved = _resolve_link(destination, source_dir)
            if resolved in existing:
                found[resolved] = LinkVia.LINK
        for found_path in find_paths(rest, source_dir, existing, path_pattern):
            # 同じ先をリンクでも取り出したときはリンクを取る
            found.setdefault(found_path, LinkVia.PATH)
    found.pop(path, None)
    targets = tuple(LinkTarget(path=key, via=found[key]) for key in sorted(found))
    return FileLinks(path=path, targets=targets)


def _resolve_link(destination: str, source_dir: str) -> str | None:
    """リンクの先を指す側のフォルダから解く。配信元の中のファイルとして解かない先は `None`。"""
    if destination.startswith(SKIP_LINK_PREFIXES):
        return None
    target = destination.split("#", 1)[0]
    if not target:
        return None
    return posixpath.normpath(posixpath.join(source_dir, target))


def collect_yaml_strings(text: str) -> list[str]:
    """YAML の文字列を読み、全ての文字列の値を返す。"""
    try:
        document = load_yaml(text)
    except YamlLoadError:
        return [text]
    values: list[str] = []
    _collect_strings(document, values)
    return values


def _collect_strings(node: object, values: list[str]) -> None:
    """辞書の値と配列の要素を深さ優先でたどり、文字列の値を `values` に足す。"""
    if isinstance(node, str):
        values.append(node)
    elif isinstance(node, dict):
        for child in cast("dict[object, object]", node).values():
            _collect_strings(child, values)
    elif isinstance(node, list):
        for child in cast("list[object]", node):
            _collect_strings(child, values)


def extract_links(text: str) -> tuple[list[str], str]:
    """文字列から Markdown のリンクの先と、リンクを同じ長さの空白に置き換えた文字列を返す。"""
    destinations: list[str] = []

    def blank(match: re.Match[str]) -> str:
        destinations.append(match.group(1))
        return " " * len(match.group(0))

    rest = LINK_PATTERN.sub(blank, text)
    return destinations, rest


def find_paths(
    text: str, source_dir: str, existing: frozenset[str], path_pattern: re.Pattern[str] | None
) -> set[str]:
    """リンクの外の文字列から、実在するファイルのパスを返す。"""
    found: set[str] = set()
    if path_pattern is not None:
        found.update(match.group(1) for match in path_pattern.finditer(text))
    for match in RELATIVE_PATTERN.finditer(text):
        resolved = resolve_relative(match.group(1), source_dir, existing)
        if resolved is not None:
            found.add(resolved)
    return found


def resolve_relative(fragment: str, source_dir: str, existing: frozenset[str]) -> str | None:
    """`./`・`../` で始まる文字列を指す側のフォルダから解き、最も長く一致する実在するファイルを返す。"""
    for end in range(len(fragment), 0, -1):
        candidate = posixpath.normpath(posixpath.join(source_dir, fragment[:end]))
        # root の外（`..` で始まる）は実在するファイルの集合に無い
        if candidate == ".." or candidate.startswith("../"):
            return None
        if candidate in existing:
            return candidate
    return None


def build_path_pattern(paths: Iterable[str]) -> re.Pattern[str] | None:
    """パスの集合を、共通の接頭辞をまとめた 1 つの正規表現にする。"""
    trie: _Trie = {}
    for path in paths:
        node = trie
        for char in path:
            node = node.setdefault(char, {})
        node[_END] = {}
    if not trie:
        return None
    body = _trie_regex(trie)
    return re.compile(f"(?<!{PATH_BOUNDARY_BEFORE})({body})(?!{PATH_BOUNDARY_AFTER})")


def _trie_regex(node: _Trie) -> str:
    """trie のノードから先を、子の文字の選択の正規表現にする。"""
    branches = [
        re.escape(char) + _trie_regex(child) for char, child in sorted(node.items()) if char
    ]
    if not branches:
        return ""
    body = branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"
    # 終端のノードの続きは省けるようにし、長い一致を先に試す
    return f"(?:{body})?" if _END in node else body


def to_json_line(file_links: FileLinks) -> str:
    """ファイルの指す先をインターフェース定義の形の 1 行の JSON にする。"""
    data = {
        "path": file_links.path,
        "targets": [
            {"path": target.path, "via": target.via.value} for target in file_links.targets
        ],
    }
    return json.dumps(data, ensure_ascii=False)

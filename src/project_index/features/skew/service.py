"""管理用の YAML と行の案の読み込み・description の類似度・偏りの洗い出しと JSON への変換。"""

from __future__ import annotations

import dataclasses
import json
import os
import posixpath
import re
import unicodedata
from itertools import combinations
from typing import TYPE_CHECKING, cast

from project_index.features.skew.types import (
    DominantTag,
    MetadataRow,
    SimilarPair,
    SingletonTag,
    SkewInputError,
    SkewResult,
)
from project_index.shared.yaml_io import YamlLoadError, load_yaml

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

# 導き方は docs/pr/113/しきい値の測定/README.md（project-index で 251 行中 29 組、0.85 だと 82 組）
SIMILARITY_THRESHOLD = 0.9
SIMILARITY_DIGITS = 3
IGNORED_CHARS = re.compile(r"[\s\W_]+")


def load_rows(
    root: Path, files_yamls: Sequence[str], *, draft: str | None = None
) -> tuple[list[MetadataRow], frozenset[str]]:
    """管理用の YAML の行と行の案を読み、行の案で置き換えた行と行の案のパスを返す。"""
    rows: dict[str, MetadataRow] = {}
    for files_yaml in files_yamls:
        for row in _read_files_yaml(root, root / files_yaml):
            rows[row.path] = row
    draft_rows = _read_draft(root / draft) if draft is not None else []
    for row in draft_rows:
        rows[row.path] = row
    draft_paths = frozenset(row.path for row in draft_rows)
    return [rows[path] for path in sorted(rows)], draft_paths


def _read_text(path: Path) -> str:
    """ファイルを読む。無いか読めなければ `SkewInputError` を送る。"""
    if not path.is_file():
        raise SkewInputError(path, "ファイルがありません")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SkewInputError(path, str(error)) from error


def _read_files_yaml(root: Path, path: Path) -> Iterator[MetadataRow]:
    """管理用の YAML の `files[]` の行を、`root` からのパスの行にして返す。"""
    try:
        data = load_yaml(_read_text(path), file=str(path))
    except YamlLoadError as error:
        raise SkewInputError(path, str(error)) from error
    files = cast("dict[str, object]", data).get("files") if isinstance(data, dict) else None
    if not isinstance(files, list):
        raise SkewInputError(path, "files が配列ではありません")
    folder = os.path.relpath(path.parent, root)
    for item in cast("list[object]", files):
        row = _to_row(item)
        if row is not None:
            joined = posixpath.normpath(posixpath.join(folder, row.path))
            yield dataclasses.replace(row, path=joined)


def _read_draft(path: Path) -> list[MetadataRow]:
    """行の案の JSON Lines を 1 行ずつ行にする。"""
    rows: list[MetadataRow] = []
    for number, line in enumerate(_read_text(path).splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise SkewInputError(path, f"{number} 行目: {error.msg}") from error
        row = _to_row(item)
        if row is None:
            raise SkewInputError(path, f"{number} 行目: path がありません")
        rows.append(row)
    return rows


def _to_row(item: object) -> MetadataRow | None:
    """管理用の YAML の行か行の案の 1 行を行にする。`path` が無ければ `None`。"""
    if not isinstance(item, dict):
        return None
    values = cast("dict[str, object]", item)
    path = values.get("path")
    if not isinstance(path, str):
        return None
    description = values.get("description")
    tags = values.get("tags")
    names = [_tag_name(tag) for tag in cast("list[object]", tags)] if isinstance(tags, list) else []
    return MetadataRow(
        path=path,
        description=description if isinstance(description, str) else None,
        tags=tuple(dict.fromkeys(name for name in names if name is not None)),
    )


def _tag_name(tag: object) -> str | None:
    """タグの要素（文字列か `{name: ...}`）から名前を返す。"""
    if isinstance(tag, str):
        return tag
    if isinstance(tag, dict):
        name = cast("dict[str, object]", tag).get("name")
        return name if isinstance(name, str) else None
    return None


def similarity(left: str, right: str) -> float:
    """2 つの description の文字 bigram の Dice 係数を返す。"""
    return _dice(_bigrams(left), _bigrams(right))


def _bigrams(text: str) -> frozenset[str]:
    """NFKC・casefold にし、空白と記号を除いた文字列の隣り合う 2 文字の集合を返す。"""
    normalized = IGNORED_CHARS.sub("", unicodedata.normalize("NFKC", text).casefold())
    if len(normalized) <= 1:
        return frozenset({normalized}) if normalized else frozenset()
    return frozenset(normalized[index : index + 2] for index in range(len(normalized) - 1))


def _dice(left: frozenset[str], right: frozenset[str]) -> float:
    """2 つの集合の Dice 係数。どちらかが空なら 0.0。"""
    if not left or not right:
        return 0.0
    return 2 * len(left & right) / (len(left) + len(right))


def find_skew(
    rows: Sequence[MetadataRow],
    *,
    draft_paths: frozenset[str] = frozenset(),
    only_draft: bool = False,
) -> SkewResult:
    """行から、ほぼ同じ description の組・1 件だけのタグ・半数以上に付くタグを返す。"""
    singletons, dominants = _skewed_tags(rows)
    return SkewResult(
        rows=len(rows),
        similar_descriptions=_similar_pairs(rows, draft_paths, only_draft=only_draft),
        singleton_tags=singletons,
        dominant_tags=dominants,
    )


def _similar_pairs(
    rows: Sequence[MetadataRow], draft_paths: frozenset[str], *, only_draft: bool
) -> tuple[SimilarPair, ...]:
    """description を持つ行の組のうち、類似度がしきい値以上の組を返す。"""
    described = [(row.path, _bigrams(row.description)) for row in rows if row.description]
    pairs: list[SimilarPair] = []
    for (left_path, left), (right_path, right) in _candidate_pairs(
        described, draft_paths, only_draft=only_draft
    ):
        score = _dice(left, right)
        if score >= SIMILARITY_THRESHOLD:
            first, second = sorted((left_path, right_path))
            pairs.append(
                SimilarPair(paths=(first, second), similarity=round(score, SIMILARITY_DIGITS))
            )
    pairs.sort(key=lambda pair: (-pair.similarity, pair.paths))
    return tuple(pairs)


type _Described = tuple[str, frozenset[str]]


def _candidate_pairs(
    described: Sequence[_Described], draft_paths: frozenset[str], *, only_draft: bool
) -> Iterator[tuple[_Described, _Described]]:
    """比べる組を返す。`only_draft` なら行の案の行を含む組だけを、各組 1 回ずつ返す。"""
    if not only_draft:
        yield from combinations(described, 2)
        return
    drafts = [index for index, (path, _) in enumerate(described) if path in draft_paths]
    draft_set = frozenset(drafts)
    for index in drafts:
        for other, item in enumerate(described):
            # 行の案どうしの組は、前の行の案を起点にしたときに返している
            if other == index or (other in draft_set and other < index):
                continue
            yield described[index], item


def _skewed_tags(
    rows: Sequence[MetadataRow],
) -> tuple[tuple[SingletonTag, ...], tuple[DominantTag, ...]]:
    """1 行だけに付くタグと、半数以上の行に付くタグ（1 行だけのタグを除く）を返す。"""
    tagged: dict[str, list[str]] = {}
    for row in rows:
        for tag in row.tags:
            tagged.setdefault(tag, []).append(row.path)
    singletons = tuple(
        SingletonTag(tag=tag, path=paths[0])
        for tag, paths in sorted(tagged.items())
        if len(paths) == 1
    )
    dominants = [
        DominantTag(tag=tag, count=len(paths))
        for tag, paths in tagged.items()
        if len(paths) > 1 and len(paths) * 2 >= len(rows)
    ]
    dominants.sort(key=lambda tag: (-tag.count, tag.tag))
    return singletons, tuple(dominants)


def to_json(result: SkewResult) -> str:
    """偏りの一覧をインターフェース定義の形の JSON にする。"""
    return json.dumps(dataclasses.asdict(result), ensure_ascii=False)

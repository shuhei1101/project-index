"""Markdown のアウトラインの取り出し。"""

from __future__ import annotations

import re

from project_index.features.outline.types import ExistingDescription, MarkdownOutline
from project_index.shared.narrowing import is_dict
from project_index.shared.yaml_io import YamlLoadError, load_yaml

FRONT_MATTER_FENCE = "---"
_CODE_FENCE = re.compile(r"^\s*(```|~~~)\s*([^\s`~]*)")
_HEADING = re.compile(r"^#{1,6}\s")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[[^\]]*\]\([^)]*\)")
_JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
# 日本語の割合を求めるときに数えない Markdown の記号
_MARKDOWN_SYMBOLS = frozenset("|-*#`[]()>:.,_/")


def outline_markdown(text: str) -> MarkdownOutline:
    """Markdown の文字列からアウトラインを取り出す。"""
    description, lines = _split_front_matter(text.splitlines())
    languages: list[str] = []
    prose: list[str] = []
    code_lines = 0
    fence: str | None = None
    for line in lines:
        match = _CODE_FENCE.match(line)
        # コードブロックの開き・閉じの行: フェンスを切り替える
        if match is not None and (fence is None or match.group(1) == fence):
            code_lines += 1
            fence = _toggle_fence(fence, match, languages)
        # コードブロックの中の行は数えるだけ
        elif fence is not None:
            code_lines += 1
        else:
            prose.append(line)
    headings = [line.rstrip() for line in prose if _HEADING.match(line)]
    prose_text = "\n".join(prose)
    images = len(_IMAGE.findall(prose_text))
    links = len(_LINK.findall(prose_text)) - images
    return MarkdownOutline(
        existing_description=description,
        headings=tuple(headings),
        code_block_ratio=code_lines / len(lines) if lines else 0,
        code_languages=tuple(languages),
        link_count=links,
        image_count=images,
        japanese_ratio=_japanese_ratio(prose_text),
    )


def _toggle_fence(fence: str | None, match: re.Match[str], languages: list[str]) -> str | None:
    """フェンスの行で、コードブロックの中と外を切り替えた後のフェンスを返す。"""
    # 閉じる行: コードブロックの外へ戻る
    if fence is not None:
        return None
    # 開く行: 後ろの単語を言語として記録する（出た順・重複なし）
    language = match.group(2)
    if language and language not in languages:
        languages.append(language)
    return match.group(1)


def _split_front_matter(lines: list[str]) -> tuple[ExistingDescription | None, list[str]]:
    """先頭のフロントマターを切り離し、既に持つ説明と本文の行を返す。"""
    # 1 行目が開く行でなければフロントマターは無い
    if not lines or lines[0].strip() != FRONT_MATTER_FENCE:
        return None, lines
    for index in range(1, len(lines)):
        if lines[index].strip() == FRONT_MATTER_FENCE:
            return _front_matter_description(lines[1:index]), lines[index + 1 :]
    # 閉じる行が無ければ、全文を本文として扱う
    return None, lines


def _front_matter_description(lines: list[str]) -> ExistingDescription | None:
    """フロントマターの `title`・`description` を既に持つ説明にする。"""
    try:
        data = load_yaml("\n".join(lines))
    except YamlLoadError:
        # 読めないフロントマターは説明にしない（本文の扱いは変えない）
        return None
    if not is_dict(data):
        return None
    title = data.get("title")
    description = data.get("description")
    title_text = title if isinstance(title, str) else None
    description_text = description if isinstance(description, str) else None
    if title_text is None and description_text is None:
        return None
    return ExistingDescription(
        source="front_matter", title=title_text, description=description_text
    )


def _japanese_ratio(text: str) -> float:
    """空白と記号を除いた文字のうち、ひらがな・カタカナ・漢字の割合を返す。"""
    chars = [char for char in text if not char.isspace() and char not in _MARKDOWN_SYMBOLS]
    if not chars:
        return 0
    return sum(1 for char in chars if _JAPANESE.match(char)) / len(chars)

"""アウトラインの対象の選択・読み取り・次の段階へ進む判定・1 行の JSON。"""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from typing import TYPE_CHECKING

from project_index.features.documents.indexable import indexable_files
from project_index.features.outline.code import (
    outline_package_json,
    outline_python,
    outline_script,
)
from project_index.features.outline.markdown import outline_markdown
from project_index.features.outline.types import (
    CodeOutline,
    FileOutline,
    MarkdownOutline,
    NextStageReason,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

MIN_HEADINGS = 2
MAX_CODE_BLOCK_RATIO = 0.5
MIN_JAPANESE_RATIO = 0.1
MAX_READ_BYTES = 1_048_576
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
SCRIPT_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"})
PACKAGE_JSON = "package.json"
# 1 行の JSON に出す割合の小数の桁数
RATIO_DIGITS = 2


def outline_files(
    root: Path, paths: Sequence[str], *, exclude: Sequence[str] = ()
) -> list[FileOutline]:
    """範囲の glob のうち載せるファイルのアウトラインを、パスの昇順で返す。"""
    return [outline_file(root, path) for path in indexable_files(root, paths, exclude=exclude)]


def outline_file(root: Path, path: str) -> FileOutline:
    """ファイル 1 つを読み、形式に合ったアウトラインと次の段階へ進む判定を返す。"""
    target = root / path
    size = target.stat().st_size
    with target.open("rb") as handle:
        text = handle.read(MAX_READ_BYTES).decode("utf-8", errors="replace")
    outline = _outline_by_format(target, text)
    reasons = judge_next_stage(outline)
    markdown = outline if isinstance(outline, MarkdownOutline) else None
    code = outline if isinstance(outline, CodeOutline) else None
    return FileOutline(
        path=path,
        size=size,
        existing_description=outline.existing_description if outline is not None else None,
        headings=markdown.headings if markdown else (),
        code_block_ratio=markdown.code_block_ratio if markdown else 0,
        code_languages=markdown.code_languages if markdown else (),
        link_count=markdown.link_count if markdown else 0,
        image_count=markdown.image_count if markdown else 0,
        japanese_ratio=markdown.japanese_ratio if markdown else 0,
        functions=code.functions if code else (),
        classes=code.classes if code else (),
        imports=code.imports if code else (),
        next_stage=bool(reasons),
        reasons=reasons,
    )


def judge_next_stage(
    outline: MarkdownOutline | CodeOutline | None,
) -> tuple[NextStageReason, ...]:
    """アウトラインから次の段階へ進む理由を返す。"""
    # 未対応の形式: アウトラインが無いので必ず進む
    if outline is None:
        return (NextStageReason.UNSUPPORTED_FORMAT,)
    # Markdown: 3 つのしきい値のどれかに当たれば進む
    if isinstance(outline, MarkdownOutline):
        reasons: list[NextStageReason] = []
        if len(outline.headings) < MIN_HEADINGS:
            reasons.append(NextStageReason.FEW_HEADINGS)
        if outline.code_block_ratio >= MAX_CODE_BLOCK_RATIO:
            reasons.append(NextStageReason.MOSTLY_CODE)
        if outline.japanese_ratio < MIN_JAPANESE_RATIO:
            reasons.append(NextStageReason.NOT_JAPANESE)
        return tuple(reasons)
    # コード: 説明も定義も無いときだけ進む
    if outline.existing_description is None and not outline.functions and not outline.classes:
        return (NextStageReason.NO_DEFINITIONS,)
    return ()


def to_json_line(outline: FileOutline) -> str:
    """ファイルのアウトラインをインターフェース定義の形の 1 行の JSON にする。"""
    data = dataclasses.asdict(outline)
    for key in ("code_block_ratio", "japanese_ratio"):
        data[key] = round(data[key], RATIO_DIGITS)
    return json.dumps(data, ensure_ascii=False, default=_json_default)


def _outline_by_format(target: Path, text: str) -> MarkdownOutline | CodeOutline | None:
    """拡張子とファイル名で形式を分け、形式に合ったアウトラインを返す。"""
    suffix = target.suffix.lower()
    if suffix in MARKDOWN_SUFFIXES:
        return outline_markdown(text)
    if suffix == ".py":
        return outline_python(text)
    if suffix in SCRIPT_SUFFIXES:
        return outline_script(text)
    if target.name == PACKAGE_JSON:
        return outline_package_json(text)
    # 未対応の形式はアウトラインを持たない
    return None


def _json_default(value: object) -> object:
    """JSON にできない値（列挙）を値の文字列にする。"""
    if isinstance(value, Enum):
        return value.value
    msg = f"JSON にできない値です: {value!r}"
    raise TypeError(msg)

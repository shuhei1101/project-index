"""関連のたどりの結果の Markdown。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.search.render import EXCLUDED_COLUMN, EXCLUDED_MARK, OUTSIDE_SCOPE_LINE

if TYPE_CHECKING:
    from project_index.features.related.types import RelatedResult


def _cell(text: str) -> str:
    """表のセルの文字列にする。"""
    return text.replace("|", "\\|").replace("\n", "<br>")


def _item_rows(result: RelatedResult) -> list[str]:
    """たどった相手の表の行を作る（除外の列は、該当する相手があるときだけ）。"""
    has_excluded = any(item.excluded for item in result.items)
    head = ["id", "深さ", "たどった関連", "name", "description"]
    head.extend([EXCLUDED_COLUMN] if has_excluded else [])
    rows = [f"| {' | '.join(head)} |", f"| {' | '.join('---' for _ in head)} |"]
    for item in result.items:
        arrow = "→" if item.via_direction == "out" else "←"
        doc_id = f"{item.source}:{item.id}" if item.source else item.id
        via = f"{item.via_from} {arrow} {item.via_type}"
        mark = [EXCLUDED_MARK if item.excluded else ""] if has_excluded else []
        cells = [_cell(doc_id), str(item.depth), _cell(via), _cell(item.name)]
        cells.extend([_cell(item.description), *mark])
        rows.append(f"| {' | '.join(cells)} |")
    return rows


def render_related_markdown(result: RelatedResult) -> str:
    """`format: markdown` の本文を作る。"""
    lines = [
        *([OUTSIDE_SCOPE_LINE] if result.outside_scope else []),
        f"{', '.join(result.start)} から {len(result.items)} 件",
        "",
    ]
    if result.items:
        lines.extend(_item_rows(result))
        lines.append("")
    if result.suggestions:
        lines.extend(["| 候補 | 信号 | 順位の値 |", "| --- | --- | --- |"])
        lines.extend(
            f"| {suggestion.id} | {', '.join(suggestion.signals)} | {suggestion.score} |"
            for suggestion in result.suggestions
        )
        lines.extend(["", "採用するときは `write_docs` で `related` に追加してください。", ""])
    lines.extend(f"> {note}" for note in result.notes)
    return "\n".join(lines).rstrip("\n") + "\n"

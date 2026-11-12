"""変更の結果の Markdown。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.search.render import OUTSIDE_SCOPE_LINE

if TYPE_CHECKING:
    from project_index.features.changes.types import ChangesResult, RangePoint


def _point(point: RangePoint) -> str:
    """区間の端を `commit（日時）` にする（commit が無ければ渡した値）。"""
    label = point.commit or point.input
    if point.date is None:
        return label
    return f"{label}（{point.date.strftime('%Y-%m-%d %H:%M')}）"


def render_changes_markdown(result: ChangesResult, *, source_label: str) -> str:
    """`format: markdown` の本文を作る。"""
    lines = [
        *([OUTSIDE_SCOPE_LINE] if result.outside_scope else []),
        f"{source_label}: {_point(result.range_from)} → {_point(result.range_to)}"
        f"・変わった文書 {result.total_count} 件",
        "",
    ]
    if result.items:
        has_source = any(item.source for item in result.items)
        has_words = any(item.contains_changes for item in result.items)
        head = [
            "id",
            *(["source"] if has_source else []),
            "変更",
            "変わったキー",
            *(["単語の増減"] if has_words else []),
        ]
        lines.extend([f"| {' | '.join(head)} |", f"| {' | '.join('---' for _ in head)} |"])
        for item in result.items:
            cells = [item.id, *([item.source or ""] if has_source else []), item.change]
            cells.append(", ".join(item.keys))
            if has_words:
                cells.append(
                    "・".join(
                        f"{change.kind} {change.to.commit or change.to.input}"
                        for change in item.contains_changes or []
                    )
                )
            lines.append(f"| {' | '.join(cells)} |")
        lines.append("")
        for item in result.items:
            if item.diff:
                lines.extend([f"## {item.id}", ""])
                block = ["```diff", item.diff, "```"]
                if item.path:
                    block = [f'<document path="{item.path}" scope="{item.scope}">', *block]
                    block.append("</document>")
                lines.extend([*block, ""])
    lines.extend(f"> {note}" for note in result.notes)
    if result.next_cursor:
        lines.append(f"続き: cursor={result.next_cursor}")
    return "\n".join(lines).rstrip("\n") + "\n"

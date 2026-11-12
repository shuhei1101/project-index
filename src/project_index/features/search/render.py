"""検索の結果の Markdown。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.shared.narrowing import is_list

if TYPE_CHECKING:
    from project_index.features.search.types import SearchItem, SearchResult, Snippet

COLUMN_TITLES = {"@chars": "chars"}
BODY_FIELD = "body"
ARRAY_JOINER = ", "
SNIPPET_SEPARATOR = "--"
HIT_MARK = ":"
CONTEXT_MARK = "-"
OUTSIDE_SCOPE_LINE = "作業範囲の外（参考）"


def _title(name: str) -> str:
    """表の列名にする（`@chars` は `chars`）。"""
    return COLUMN_TITLES.get(name, name.removeprefix("@"))


def _cell(value: object) -> str:
    """表のセルの文字列にする。"""
    if value is None:
        return ""
    if is_list(value):
        return ARRAY_JOINER.join(str(item) for item in value)
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _table(result: SearchResult) -> list[str]:
    """項目を列にした表を作る。"""
    has_source = any(item.source for item in result.items)
    columns = ["id", *(["source"] if has_source else [])]
    for item in result.items:
        columns.extend(name for name in item.values if name not in columns)
    lines = [
        f"| {' | '.join(_title(name) for name in columns)} |",
        f"| {' | '.join('---' for _ in columns)} |",
    ]
    for item in result.items:
        cells = {"id": item.id, "source": item.source, **item.values}
        lines.append(f"| {' | '.join(_cell(cells.get(name)) for name in columns)} |")
    return lines


def _snippet_lines(snippets: list[Snippet]) -> list[str]:
    """抜粋を grep の `-n` と同じ書式の行にする（当たった行は `:`、前後の行は `-`、抜粋の間は `--`）。"""
    lines: list[str] = []
    for index, snippet in enumerate(snippets):
        if index > 0:
            lines.append(SNIPPET_SEPARATOR)
        lines.extend(
            f"{line.line}{HIT_MARK if line.hit else CONTEXT_MARK}{line.text}"
            for line in snippet.lines
        )
    return lines


def _range_line(item: SearchItem) -> str:
    """切り出した範囲と本文の全体の行数を `<document>` の前の行にする。"""
    if not item.ranges:
        return f"{item.id}: 返却する行なし / 全 {item.total_lines} 行"
    spans = "・".join(f"{span.start_line}-{span.end_line} 行目" for span in item.ranges)
    return f"{item.id}: {spans} / 全 {item.total_lines} 行"


def _full(item: SearchItem, *, outside_scope: bool = False) -> list[str]:
    """`view: full` の文書 1 件を、`<document>` で包んだ項目の箇条書きと本文にする。"""
    attributes = f' path="{item.path}" scope="{item.scope}"' if item.path else ""
    if outside_scope:
        attributes += ' outside_scope="true"'
    lines = [f"<document{attributes}>", f"- id: {item.id}"]
    if item.total_lines is not None:
        lines.insert(0, _range_line(item))
    if item.source:
        lines.append(f"- source: {item.source}")
    body = item.values.get(BODY_FIELD)
    lines.extend(
        f"- {_title(name)}: {_cell(value)}"
        for name, value in item.values.items()
        if name != BODY_FIELD
    )
    if item.snippets:
        lines.append("")
        lines.extend(_snippet_lines(item.snippets))
    if isinstance(body, str):
        lines.append("")
        lines.append(body.rstrip("\n"))
    lines.append("</document>")
    return lines


def render_search_markdown(result: SearchResult, *, source_label: str) -> str:
    """`format: markdown` の本文を作る。"""
    head = f"{source_label}: 該当 {result.total_count} 件・返却した {result.returned} 件"
    if result.per_source:
        counts = "・".join(f"{name} {count} 件" for name, count in result.per_source.items())
        head += f"（{counts}）"
    lines = [*([OUTSIDE_SCOPE_LINE] if result.outside_scope else []), head, ""]
    if result.groups:
        lines.extend(["| 値 | 件数 |", "| --- | --- |"])
        lines.extend(f"| {_cell(group.value)} | {group.count} |" for group in result.groups)
        lines.append("")
    if result.items:
        if result.view == "full":
            for item in result.items:
                lines.extend(_full(item, outside_scope=result.outside_scope))
                lines.append("")
        else:
            lines.extend(_table(result))
            lines.append("")
    lines.extend(f"> {note}" for note in result.notes)
    if result.next_cursor:
        lines.append(f"続き: cursor={result.next_cursor}")
    return "\n".join(lines).rstrip("\n") + "\n"

"""説明の Markdown。"""

from __future__ import annotations

from project_index.features.describe.types import (
    KindSchemaResult,
    SourceGuideResult,
    SourceListResult,
)
from project_index.features.search.render import OUTSIDE_SCOPE_LINE

OUTSIDE_NONE_LINE = "なし"
NO_SOURCE_LINE = (
    "使用できる配信元はありません。配信元にするときは /project-index:setup を実行します。"
)
WARNINGS_LINE = "注意:"


def _cell(text: str) -> str:
    """表のセルの文字列にする。"""
    return text.replace("|", "\\|").replace("\n", "<br>")


def _place(result: SourceListResult) -> str:
    """作業場所の行を作る。"""
    workplace = result.workplace
    if workplace.source_id is None:
        return f"作業場所: {workplace.cwd}（どの配信元の中でもありません）"
    kind = "ワークツリー" if workplace.worktree is not None else "クローン本体"
    return f"作業場所: {workplace.cwd}（{workplace.source_id} の{kind}）"


def render_describe_markdown(
    result: SourceListResult | SourceGuideResult | KindSchemaResult,
) -> str:
    """`format: markdown` の本文を作る。"""
    if isinstance(result, SourceListResult):
        lines = [_place(result), ""]
        if result.sources:
            lines.extend(["| source | 権限 | description |", "| --- | --- | --- |"])
            for item in result.sources:
                access = f"{item.access}（作業中）" if item.current else item.access
                lines.append(f"| {_cell(item.source_id)} | {access} | {_cell(item.description)} |")
        else:
            lines.append(NO_SOURCE_LINE)
        # 作業範囲の外の一覧を求められたときだけ、表か「なし」を続ける
        if result.outside_sources is not None:
            lines.extend(["", OUTSIDE_SCOPE_LINE])
            if result.outside_sources:
                lines.extend(["| source | description |", "| --- | --- |"])
                lines.extend(
                    f"| {_cell(item.id)} | {_cell(item.description)} |"
                    for item in result.outside_sources
                )
            else:
                lines.append(OUTSIDE_NONE_LINE)
        if result.warnings:
            lines.extend(["", WARNINGS_LINE])
            lines.extend(f"- {warning}" for warning in result.warnings)
        return "\n".join(lines) + "\n"
    head = [OUTSIDE_SCOPE_LINE] if result.outside_scope else []
    if isinstance(result, SourceGuideResult):
        lines = [*head, result.instructions, "", "| kind | description |", "| --- | --- |"]
        lines.extend(f"| {_cell(kind.id)} | {_cell(kind.description)} |" for kind in result.kinds)
        if result.refs is not None:
            lines.extend(
                [
                    "",
                    f"ブランチ: {', '.join(result.refs.get('branches', []))}",
                    f"タグ: {', '.join(result.refs.get('tags', []))}",
                ]
            )
        if result.worktrees:
            lines.extend(["", "| ワークツリー | ブランチ |", "| --- | --- |"])
            lines.extend(
                f"| {_cell(item.path)} | {_cell(item.branch or '')} |" for item in result.worktrees
            )
        return "\n".join(lines) + "\n"
    lines = list(head)
    if result.metadata:
        lines = ["| 共通のキー | 列名 |", "| --- | --- |"]
        lines.extend(
            f"| {_cell(key)} | {_cell(column)} |" for key, column in result.metadata.items()
        )
        lines.append("")
    lines.append(f"```yaml\n{result.schema_text.rstrip(chr(10))}\n```")
    return "\n".join(lines) + "\n"

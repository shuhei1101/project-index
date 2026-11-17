from __future__ import annotations

from pathlib import Path

from project_index.features.access.types import SourceAccess, Workplace
from project_index.features.describe.render import render_describe_markdown
from project_index.features.describe.types import (
    KindSchemaResult,
    OutsideSource,
    SourceGuideResult,
    SourceListResult,
)


def test_render_describe_markdown_when_source_when() -> None:
    """使う場面の列と見出し（正常系）。"""
    # 準備
    listed = SourceListResult(
        workplace=Workplace(cwd=Path("/w/sample"), source_id="sample", worktree=None),
        sources=[
            SourceAccess(
                source_id="sample",
                access="write",
                current=True,
                description="サンプル",
                when=["規約を確かめるとき", "設計書を書く前"],
            ),
            SourceAccess(source_id="notes", access="read", current=False, description="メモ"),
        ],
        outside_sources=[OutsideSource(id="other", description="別", when=["別を引くとき"])],
    )
    guide = SourceGuideResult(
        source_id="sample",
        instructions="着手前に規約を引く",
        kinds=[],
        when=["規約を確かめるとき", "設計書を書く前"],
    )
    plain = SourceGuideResult(source_id="sample", instructions="着手前に規約を引く", kinds=[])
    # 実行
    listed_markdown = render_describe_markdown(listed)
    guide_lines = render_describe_markdown(guide).splitlines()
    plain_markdown = render_describe_markdown(plain)
    # 検証
    assert "| source | 権限 | description | when |" in listed_markdown
    assert "| sample | write（作業中） | サンプル | 規約を確かめるとき<br>設計書を書く前 |" in (
        listed_markdown
    )
    assert "| notes | read | メモ |  |" in listed_markdown
    assert "| other | 別 | 別を引くとき |" in listed_markdown
    assert guide_lines.index("使う場面:") < guide_lines.index("着手前に規約を引く")
    assert "- 規約を確かめるとき" in guide_lines
    assert "- 設計書を書く前" in guide_lines
    assert "使う場面:" not in plain_markdown


def test_render_describe_markdown() -> None:
    """一覧の表（正常系）。"""
    # 準備
    result = SourceListResult(
        workplace=Workplace(cwd=Path("/w/sample"), source_id="sample", worktree=None),
        sources=[
            SourceAccess(source_id="sample", access="write", current=True, description="サンプル"),
            SourceAccess(source_id="notes", access="read", current=False, description="メモ"),
        ],
    )
    # 実行
    markdown = render_describe_markdown(result)
    # 検証
    assert "| sample | write（作業中） | サンプル |" in markdown
    assert "| notes | read | メモ |" in markdown


def test_render_describe_markdown_when_warnings() -> None:
    """注意の一覧（正常系）。"""
    # 準備
    workplace = Workplace(cwd=Path("/w/sample"), source_id="sample", worktree=None)
    sources = [
        SourceAccess(source_id="sample", access="write", current=True, description="サンプル")
    ]
    warned = SourceListResult(workplace=workplace, sources=sources, warnings=["警告です"])
    quiet = SourceListResult(workplace=workplace, sources=sources)
    # 実行
    markdown = render_describe_markdown(warned)
    quiet_markdown = render_describe_markdown(quiet)
    # 検証
    lines = markdown.splitlines()
    assert lines.index("注意:") > lines.index("| sample | write（作業中） | サンプル |  |")
    assert "- 警告です" in lines
    assert "注意:" not in quiet_markdown


def test_render_describe_markdown_when_no_source() -> None:
    """使える配信元が無い（正常系）。"""
    # 準備
    result = SourceListResult(
        workplace=Workplace(cwd=Path("/w/elsewhere"), source_id=None, worktree=None),
        sources=[],
        warnings=["b: 配信していません"],
    )
    # 実行
    markdown = render_describe_markdown(result)
    # 検証
    assert "| source | 権限 | description |" not in markdown
    assert "/project-index:setup" in markdown
    assert "注意:" in markdown
    assert "- b: 配信していません" in markdown


def test_render_describe_markdown_when_outside_sources() -> None:
    """作業範囲の外で参照できる配信元の表（正常系）。"""
    # 準備
    workplace = Workplace(cwd=Path("/w/sample"), source_id="sample", worktree=None)
    sources = [
        SourceAccess(source_id="sample", access="write", current=True, description="サンプル")
    ]
    result = SourceListResult(
        workplace=workplace,
        sources=sources,
        outside_sources=[OutsideSource(id="other", description="別の配信元")],
    )
    # 実行
    markdown = render_describe_markdown(result)
    plain = render_describe_markdown(SourceListResult(workplace=workplace, sources=sources))
    # 検証
    assert markdown.index("| sample | write（作業中） | サンプル |") < markdown.index(
        "作業範囲の外（参考）"
    )
    assert "| other | 別の配信元 |" in markdown
    assert "作業範囲の外（参考）" not in plain


def test_render_describe_markdown_when_outside_sources_empty() -> None:
    """作業範囲の外で参照できる配信元が 0 件（正常系）。"""
    # 準備
    result = SourceListResult(
        workplace=Workplace(cwd=Path("/w/sample"), source_id="sample", worktree=None),
        sources=[],
        outside_sources=[],
    )
    # 実行
    markdown = render_describe_markdown(result)
    # 検証
    lines = markdown.splitlines()
    index = lines.index("作業範囲の外（参考）")
    assert lines[index + 1] == "なし"
    assert "| source | description |" not in markdown


def test_render_describe_markdown_when_metadata() -> None:
    """メタデータの対応の表（正常系）。"""
    # 準備
    result = KindSchemaResult(
        source_id="sample",
        kind="rules",
        schema_text="type: object\n",
        schema={"type": "object"},
        metadata={"name": "title"},
    )
    # 実行
    markdown = render_describe_markdown(result)
    # 検証
    assert "| name | title |" in markdown
    assert markdown.index("| name | title |") < markdown.index("```yaml")


def test_render_describe_markdown_when_outside_scope() -> None:
    """作業範囲の外の表示（正常系）。"""
    from project_index.features.describe.types import KindSummary, SourceGuideResult

    # 準備
    result = SourceGuideResult(
        source_id="other",
        instructions="other の説明書",
        kinds=[KindSummary(id="rules", description="規約")],
        outside_scope=True,
        refs=None,
        worktrees=None,
    )
    # 実行
    markdown = render_describe_markdown(result)
    # 検証
    lines = markdown.splitlines()
    assert lines[0] == "作業範囲の外（参考）"
    assert "other の説明書" in lines[1:]

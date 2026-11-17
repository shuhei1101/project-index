from __future__ import annotations

from project_index.features.outline.markdown import outline_markdown


def test_outline_markdown() -> None:
    """見出し・コードブロック・リンク・画像・日本語の割合を取り出す（正常系）。"""
    # 準備
    text = (
        "# タスクの保存\n"
        "\n"
        "タスクを保存する仕組みの説明です。[設定](./設定.md) と [用語](./用語.md) を参照します。\n"
        "\n"
        "![構成](./images/a.png)\n"
        "\n"
        "## 保存の流れ\n"
        "\n"
        "```python\n"
        "# 見出しではない\n"
        "save()\n"
        "```\n"
        "\n"
        "## 読み込みの流れ\n"
        "\n"
        "保存したタスクを読み込みます。\n"
    )
    # 実行
    result = outline_markdown(text)
    # 検証
    assert result.headings == ("# タスクの保存", "## 保存の流れ", "## 読み込みの流れ")
    assert result.code_languages == ("python",)
    assert result.link_count == 2
    assert result.image_count == 1
    assert result.japanese_ratio > 0.5
    assert result.existing_description is None


def test_outline_markdown_when_front_matter() -> None:
    """フロントマターの説明を取り出し、見出しから除く（正常系）。"""
    # 準備
    text = "---\ntitle: A\ndescription: B\n# x\n---\n\n# 本文の見出し\n\n本文です。\n"
    # 実行
    result = outline_markdown(text)
    # 検証
    assert result.existing_description is not None
    assert result.existing_description.source == "front_matter"
    assert result.existing_description.title == "A"
    assert result.existing_description.description == "B"
    assert result.headings == ("# 本文の見出し",)


def test_outline_markdown_when_front_matter_unreadable() -> None:
    """読めないフロントマターは説明にしない（正常系）。"""
    # 準備
    text = "---\n: :\n---\n\n# 見出し\n"
    # 実行
    result = outline_markdown(text)
    # 検証
    assert result.existing_description is None


def test_outline_markdown_when_mostly_code() -> None:
    """コードブロックの割合（正常系）。"""
    # 準備
    text = "# ログ\n\n```text\nline1\nline2\nline3\nline4\nline5\nline6\n```\n"
    # 実行
    result = outline_markdown(text)
    # 検証
    assert result.code_block_ratio == 0.8


def test_outline_markdown_when_english() -> None:
    """英語の本文（正常系）。"""
    # 準備
    text = "# Guide\n\nThis page explains how to use the tool.\n"
    # 実行
    result = outline_markdown(text)
    # 検証
    assert result.japanese_ratio == 0


def test_outline_markdown_when_empty() -> None:
    """空の本文（正常系）。"""
    # 実行
    result = outline_markdown("")
    # 検証
    assert result.headings == ()
    assert result.code_block_ratio == 0
    assert result.japanese_ratio == 0

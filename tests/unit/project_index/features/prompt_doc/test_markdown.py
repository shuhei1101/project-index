from __future__ import annotations

import re
from typing import Any

import pytest
from project_index.features.prompt_doc.markdown import (
    convert_prompt,
    example_body,
    lang_tabs,
    languages,
    prompt_to_markdown,
    template_html,
    var_table,
)
from project_index.features.prompt_doc.types import (
    InvalidPrompt,
    PromptDoc,
    PromptVar,
    PromptYamlError,
    RenderedExample,
    RenderedMessage,
)
from project_index.shared.yaml_io import load_yaml

# 描画結果の変数の値を囲む区切り（`VALUE_MARK_PATTERN` が当てる私用領域の文字）
MARK_START = ""
MARK_SEP = ""
MARK_END = ""


def _doc(**overrides: Any) -> PromptDoc:
    """変換に使うキーだけを持つプロンプトを作る。"""
    data: dict[str, Any] = {"name": "N", "kind": "llm", "lang": "en", "vars": {}, "parts": []}
    data.update(overrides)
    return PromptDoc.model_validate(data)


def _section(markdown: str, heading: str) -> str:
    """見出しの行から、次の同じ深さか浅い見出しの前までを返す。"""
    level = heading.split(" ", 1)[0]
    start = markdown.index(f"\n{heading}\n")
    pattern = re.compile(rf"\n#{{1,{len(level)}}} ")
    found = pattern.search(markdown, start + 1)
    return markdown[start : found.start() if found else len(markdown)]


def test_convert_prompt(reflection_yaml: str) -> None:
    """LLM のプロンプトを変換する（正常系）。"""
    # 実行
    result = convert_prompt(reflection_yaml)
    # 検証
    assert result.startswith("# 振り返りのノード")
    assert result.index("## 変数") < result.index("## テンプレート") < result.index("## 例")


def test_convert_prompt_when_yaml_unreadable() -> None:
    """読めない YAML（異常系）。"""
    # 実行・検証
    with pytest.raises(PromptYamlError, match=r"\d+:\d+"):
        convert_prompt("name: [")


def test_convert_prompt_when_required_key_missing(reflection_without_parts_yaml: str) -> None:
    """parts が無い（異常系）。"""
    # 実行・検証
    with pytest.raises(InvalidPrompt, match=r"^parts:"):
        convert_prompt(reflection_without_parts_yaml)


def test_convert_prompt_when_texts_invalid() -> None:
    """入れ子のキーの型が違う（異常系）。"""
    # 準備
    text = "name: N\nkind: llm\nlang: en\nparts:\n  - id: a\n    texts: oops\n"
    # 実行・検証
    with pytest.raises(InvalidPrompt, match=r"parts\[0\]\.texts"):
        convert_prompt(text)


def test_prompt_to_markdown(reflection_yaml: str) -> None:
    """見出しとセクションの並び（正常系）。"""
    # 準備
    doc = PromptDoc.model_validate(load_yaml(reflection_yaml))
    # 実行
    result = prompt_to_markdown(doc)
    # 検証
    assert "badge:kind: llm" in result
    assert "badge:lang: en" in result
    assert result.index("\n### 既定の例\n") < result.index("\n### ログが無い\n")
    assert re.search(r"\n### ログが無い\n+<!-- section: closed -->\n", result)
    assert (
        result.index("\n### role\n")
        < result.index("\n### now\n")
        < result.index("\n### traits\n")
        < result.index("\n### logs\n")
        < result.index("\n### no-logs\n")
    )


def test_prompt_to_markdown_when_part_syntax_invalid(reflection_yaml: str) -> None:
    """構文の誤った部品だけを注意書きにする（正常系）。"""
    # 準備
    data = load_yaml(reflection_yaml)
    data["parts"][3]["texts"][0]["text"] = "{% if logs %}\n- {{ logs }}\n"
    doc = PromptDoc.model_validate(data)
    # 実行
    result = prompt_to_markdown(doc)
    # 検証
    assert "[!CAUTION]" in _section(result, "### logs")
    assert "[!CAUTION]" in _section(result, "### 既定の例")
    assert "[!CAUTION]" in _section(result, "### ログが無い")
    assert "[!CAUTION]" not in _section(result, "### role")
    assert "traits[].name" in _section(result, "## 変数")


def test_var_table() -> None:
    """入れ子のパスと例（正常系）。"""
    # 準備
    vars_ = {
        "traits": PromptVar.model_validate(
            {
                "type": "array",
                "example": [{"name": "好奇心"}],
                "items": {"type": "object", "properties": {"name": {"type": "string"}}},
            }
        )
    }
    # 実行
    result = var_table(vars_)
    # 検証
    assert result[0] == "| 変数 | 型 | 必須 | 例 | 説明 | 出典 |"
    assert "[{name: 好奇心}]" in result[2]
    assert "traits[].name" in result[3]


def test_template_html() -> None:
    """変数にヒントを付ける（正常系）。"""
    # 準備
    paths = {
        "character.display_name": PromptVar.model_validate(
            {"type": "string", "description": "表示名", "example": "ひな"}
        )
    }
    # 実行
    result = template_html("こんにちは {{ character.display_name }}", paths=paths)
    # 検証
    assert result.startswith("<pre><code>")
    assert (
        '<span data-hint="表示名（型: string、例: ひな）">{{ character.display_name }}</span>'
        in result
    )


def test_template_html_when_loop_variable() -> None:
    """ループの変数を配列の要素のパスに読み替える（正常系）。"""
    # 準備
    paths = {
        "traits[].name": PromptVar.model_validate(
            {"type": "string", "description": "特性の名前", "example": "好奇心"}
        )
    }
    # 実行
    result = template_html("{% for t in traits %}{{ t.name }}{% endfor %}", paths=paths)
    # 検証
    assert '<span data-hint="特性の名前（型: string、例: 好奇心）">{{ t.name }}</span>' in result


def test_template_html_when_html_in_text() -> None:
    """本文のタグをエスケープする（正常系）。"""
    # 実行
    result = template_html("<rules>a < b</rules>", paths={})
    # 検証
    assert "&lt;rules&gt;a &lt; b&lt;/rules&gt;" in result


def test_example_body() -> None:
    """役割ごとの本文と字数の行（正常系）。"""
    # 準備
    marked = (
        f"<rules>{MARK_START}character.display_name{MARK_SEP}ひな{MARK_END} "
        f"{MARK_START}reading{MARK_SEP}ruby{MARK_END}</rules>"
    )
    rendered = RenderedExample(
        messages=[
            RenderedMessage(role="system", text="Role", marked="Role"),
            RenderedMessage(role="user", text="<rules>ひな ruby</rules>", marked=marked),
        ],
        unused=[],
        char_count=26,
        problems=[],
    )
    paths = {
        "character.display_name": PromptVar.model_validate({"description": "表示名"}),
        "reading": PromptVar.model_validate({"description": '"読み"'}),
    }
    # 実行
    result = "\n".join(example_body(rendered, doc=_doc(), lang="en", paths=paths))
    # 検証
    assert "**system**" in result
    assert "**user**" in result
    assert "&lt;rules&gt;" in result
    assert '<mark data-hint="character.display_name: 表示名">ひな</mark>' in result
    assert "&quot;読み&quot;" in result
    assert "注入する本文（en）: 26 字" in result


def test_example_body_when_problems() -> None:
    """描画できない組（正常系）。"""
    # 準備
    rendered = RenderedExample(
        messages=[],
        unused=[],
        char_count=0,
        problems=["`traits` は array ですが、`oops` が入っています"],
    )
    # 実行
    result = "\n".join(example_body(rendered, doc=_doc(), lang="en", paths={}))
    # 検証
    assert "> [!CAUTION]" in result
    assert "`traits` は array ですが、`oops` が入っています" in result
    assert "<pre>" not in result


def test_example_body_when_hook_over_limit() -> None:
    """フックの字数が上限を超える（正常系）。"""
    # 準備
    rendered = RenderedExample(
        messages=[RenderedMessage(role=None, text="本文", marked="本文")],
        unused=[],
        char_count=1001,
        problems=[],
    )
    # 実行
    result = "\n".join(
        example_body(rendered, doc=_doc(kind="hook", lang="ja"), lang="ja", paths={})
    )
    # 検証
    assert "> [!WARNING]" in result
    assert "1,001" in result
    assert "1,000" in result
    assert "本文" in result


def test_example_body_when_hook_at_limit() -> None:
    """字数がちょうど上限（正常系）。"""
    # 準備
    rendered = RenderedExample(
        messages=[RenderedMessage(role=None, text="本文", marked="本文")],
        unused=[],
        char_count=1000,
        problems=[],
    )
    # 実行
    result = "\n".join(
        example_body(rendered, doc=_doc(kind="hook", lang="ja"), lang="ja", paths={})
    )
    # 検証
    assert "[!WARNING]" not in result


def test_lang_tabs() -> None:
    """言語が 2 つ（正常系）。"""
    # 実行
    result = "\n".join(lang_tabs(["en", "ja"], lambda lang: [f"body-{lang}"]))
    # 検証
    assert (
        result.index("<!-- tabs: group=lang -->")
        < result.index("#### en")
        < result.index("#### ja")
        < result.index("<!-- /tabs -->")
    )


def test_lang_tabs_when_single_language() -> None:
    """言語が 1 つ（正常系）。"""
    # 実行
    result = lang_tabs(["ja"], lambda lang: [f"body-{lang}"])
    # 検証
    assert result == ["body-ja"]


def test_languages() -> None:
    """注入する言語を先頭にする（正常系）。"""
    # 準備
    doc = _doc(
        parts=[{"id": "a", "texts": [{"lang": "ja", "text": "あ"}, {"lang": "en", "text": "a"}]}]
    )
    # 実行
    result = languages(doc)
    # 検証
    assert result == ["en", "ja"]

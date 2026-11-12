from __future__ import annotations

from typing import Any

import jinja2
import pytest

from project_index.features.prompt_doc.render import (
    TracedStr,
    build_environment,
    build_values,
    compile_parts,
    flatten_vars,
    render_example,
)
from project_index.features.prompt_doc.types import PartSyntaxError, PromptDoc, PromptVar

# 描画結果の変数の値を囲む区切り（`VALUE_MARK_PATTERN` が当てる私用領域の文字）
MARK_START = ""
MARK_SEP = ""
MARK_END = ""


def _doc(**overrides: Any) -> PromptDoc:
    """変換に使うキーだけを持つプロンプトを作る。"""
    data: dict[str, Any] = {"name": "N", "kind": "llm", "lang": "en", "vars": {}, "parts": []}
    data.update(overrides)
    return PromptDoc.model_validate(data)


# 部品 role（system）・now（user）・logs（user、when: logs）を持つ LLM のプロンプト
LLM_PARTS = [
    {"id": "role", "role": "system", "texts": [{"lang": "en", "text": "Role"}]},
    {"id": "now", "role": "user", "texts": [{"lang": "en", "text": "Now"}]},
    {
        "id": "logs",
        "role": "user",
        "when": "logs",
        "texts": [{"lang": "en", "text": "{% for line in logs %}- {{ line }}\n{% endfor %}"}],
    },
]
LLM_VARS = {"logs": {"type": "array", "example": ["a log"], "items": {"type": "string"}}}


def test_flatten_vars() -> None:
    """配列とオブジェクトを辿る（正常系）。"""
    # 準備
    vars_ = {
        "character": PromptVar.model_validate(
            {"type": "object", "properties": {"display_name": {"type": "string"}}}
        ),
        "traits": PromptVar.model_validate(
            {
                "type": "array",
                "items": {"type": "object", "properties": {"name": {"type": "string"}}},
            }
        ),
    }
    # 実行
    result = flatten_vars(vars_)
    # 検証
    assert [path for path, _ in result] == [
        "character",
        "character.display_name",
        "traits",
        "traits[].name",
    ]


def test_build_environment() -> None:
    """未定義の変数を誤りにし、ブロックの改行を削る（正常系）。"""
    # 準備
    env = build_environment()
    loop = env.from_string("{% for x in xs %}\n- {{ x }}\n{% endfor %}\n")
    undefined = env.from_string("{{ y }}")
    # 実行
    result = loop.render(xs=["a"])
    # 検証
    assert result == "- a\n"
    with pytest.raises(jinja2.UndefinedError):
        undefined.render()


def test_build_environment_when_traced() -> None:
    """パス付きの値だけを区切りで囲む（正常系）。"""
    # 準備
    template = build_environment().from_string("{{ a }}/{{ b }}")
    # 実行
    result = template.render(a=TracedStr("x", path="a"), b="y")
    # 検証
    assert result == f"{MARK_START}a{MARK_SEP}x{MARK_END}/y"


def test_build_values() -> None:
    """省いた変数を example で埋め、パスを持たせる（正常系）。"""
    # 準備
    vars_ = {
        "character": PromptVar.model_validate(
            {
                "type": "object",
                "example": {"display_name": "ひな"},
                "properties": {"display_name": {"type": "string", "example": "ひな"}},
            }
        ),
        "traits": PromptVar.model_validate(
            {
                "type": "array",
                "example": [{"name": "好奇心"}],
                "items": {"type": "object", "properties": {"name": {"type": "string"}}},
            }
        ),
    }
    # 実行
    values, problems = build_values(vars_, {"traits": [{"name": "勤勉さ"}]})
    # 検証
    assert values["character"]["display_name"] == "ひな"
    assert values["character"]["display_name"].path == "character.display_name"
    assert values["traits"][0]["name"] == "勤勉さ"
    assert values["traits"][0]["name"].path == "traits[].name"
    assert problems == []


def test_build_values_when_type_mismatch() -> None:
    """型の合わない値（異常系）。"""
    # 準備
    vars_ = {"traits": PromptVar.model_validate({"type": "array", "items": {"type": "string"}})}
    # 実行
    _, problems = build_values(vars_, {"traits": "oops"})
    # 検証
    assert problems == ["`traits` は array ですが、`oops` が入っています"]


def test_compile_parts() -> None:
    """部品ごとにテンプレートにする（正常系）。"""
    # 準備
    doc = _doc(
        parts=[
            {
                "id": "logs",
                "when": "logs",
                "texts": [{"lang": "en", "text": "Logs"}, {"lang": "ja", "text": "ログ"}],
            }
        ]
    )
    # 実行
    compiled, errors = compile_parts(doc, env=build_environment())
    # 検証
    assert compiled["logs"].when is not None
    assert sorted(compiled["logs"].texts) == ["en", "ja"]
    assert errors == []


def test_compile_parts_when_syntax_error() -> None:
    """構文の誤った本文（異常系）。"""
    # 準備
    doc = _doc(parts=[{"id": "logs", "texts": [{"lang": "en", "text": "{% if logs %}x"}]}])
    # 実行
    compiled, errors = compile_parts(doc, env=build_environment())
    # 検証
    assert "logs" not in compiled
    assert len(errors) == 1
    assert errors[0].part_id == "logs"
    assert errors[0].field == "texts[en]"
    assert errors[0].line is not None


def test_compile_parts_when_condition_braced() -> None:
    """`{{ }}` で囲んだ when（正常系）。"""
    # 準備
    doc = _doc(
        parts=[
            {
                "id": "logs",
                "when": "{{ logs | length > 0 }}",
                "texts": [{"lang": "en", "text": "Logs"}],
            }
        ]
    )
    # 実行
    compiled, errors = compile_parts(doc, env=build_environment())
    # 検証
    when = compiled["logs"].when
    assert when is not None
    assert when(logs=["a"]) is True
    assert when(logs=[]) is False
    assert errors == []


def test_render_example() -> None:
    """既定の例を役割ごとに描画する（正常系）。"""
    # 準備
    doc = _doc(vars=LLM_VARS, parts=LLM_PARTS)
    compiled, errors = compile_parts(doc, env=build_environment())
    # 実行
    result = render_example(doc, compiled=compiled, syntax_errors=errors, values={}, lang="en")
    # 検証
    assert [message.role for message in result.messages] == ["system", "user"]
    assert "a log" in result.messages[1].text
    assert f"{MARK_START}logs[]{MARK_SEP}a log{MARK_END}" in result.messages[1].marked
    assert MARK_START not in result.messages[1].text
    assert result.unused == []
    assert result.char_count == len(result.messages[0].text) + len(result.messages[1].text)
    assert result.problems == []


def test_render_example_when_condition_false() -> None:
    """when が偽の部品を使わない（正常系）。"""
    # 準備
    doc = _doc(vars=LLM_VARS, parts=LLM_PARTS)
    compiled, errors = compile_parts(doc, env=build_environment())
    # 実行
    result = render_example(
        doc, compiled=compiled, syntax_errors=errors, values={"logs": []}, lang="en"
    )
    # 検証
    assert result.unused == ["logs"]


def test_render_example_when_hook() -> None:
    """フックは 1 件につなぐ（正常系）。"""
    # 準備
    doc = _doc(
        kind="hook",
        lang="ja",
        parts=[
            {"id": "first", "texts": [{"lang": "ja", "text": "はじめ\n"}]},
            {"id": "second", "texts": [{"lang": "ja", "text": "おわり\n"}]},
        ],
    )
    compiled, errors = compile_parts(doc, env=build_environment())
    # 実行
    result = render_example(doc, compiled=compiled, syntax_errors=errors, values={}, lang="ja")
    # 検証
    assert len(result.messages) == 1
    assert result.messages[0].role is None
    assert result.messages[0].text.index("はじめ") < result.messages[0].text.index("おわり")


def test_render_example_when_lang_missing() -> None:
    """その言語の本文が無い部品（正常系）。"""
    # 準備
    doc = _doc(
        parts=[
            {
                "id": "main",
                "role": "user",
                "texts": [{"lang": "en", "text": "Main"}, {"lang": "ja", "text": "本文"}],
            },
            {"id": "note", "role": "user", "texts": [{"lang": "en", "text": "Note"}]},
        ]
    )
    compiled, errors = compile_parts(doc, env=build_environment())
    # 実行
    result = render_example(doc, compiled=compiled, syntax_errors=errors, values={}, lang="ja")
    # 検証
    assert result.unused == ["note（ja の本文なし）"]


def test_render_example_when_undefined() -> None:
    """未定義の変数（異常系）。"""
    # 準備
    doc = _doc(
        parts=[{"id": "main", "role": "user", "texts": [{"lang": "en", "text": "{{ missing }}"}]}]
    )
    compiled, errors = compile_parts(doc, env=build_environment())
    # 実行
    result = render_example(doc, compiled=compiled, syntax_errors=errors, values={}, lang="en")
    # 検証
    assert len(result.problems) == 1
    assert "missing" in result.problems[0]
    assert result.messages == []


def test_render_example_when_syntax_error() -> None:
    """構文の誤った部品がある（異常系）。"""
    # 準備
    doc = _doc(vars=LLM_VARS, parts=LLM_PARTS)
    compiled, _ = compile_parts(doc, env=build_environment())
    syntax_errors = [
        PartSyntaxError(part_id="logs", field="texts[en]", line=3, message="unexpected end")
    ]
    # 実行
    result = render_example(
        doc, compiled=compiled, syntax_errors=syntax_errors, values={}, lang="en"
    )
    # 検証
    assert len(result.problems) == 1
    assert "logs" in result.problems[0]
    assert "3" in result.problems[0]
    assert result.messages == []


def test_render_example_when_runtime_error() -> None:
    """描画中の例外（異常系）。"""
    # 準備
    doc = _doc(
        vars={"a": {"example": "x"}},
        parts=[{"id": "main", "role": "user", "texts": [{"lang": "en", "text": "{{ a + 1 }}"}]}],
    )
    compiled, errors = compile_parts(doc, env=build_environment())
    # 実行
    result = render_example(doc, compiled=compiled, syntax_errors=errors, values={}, lang="en")
    # 検証
    assert len(result.problems) == 1
    assert "TypeError" in result.problems[0]
    assert result.messages == []

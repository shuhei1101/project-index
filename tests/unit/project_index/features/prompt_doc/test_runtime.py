from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.prompt_doc.runtime import (
    DEFAULT_PROMPTS_DIR,
    load_prompts,
    prompts_dir,
)
from project_index.features.prompt_doc.types import PromptInvalidError
from project_index.server.mcp.result import DOCS_INSTRUCTIONS_PROMPT_ID, mcp_prompt_ids

if TYPE_CHECKING:
    from pathlib import Path

# 本文に置かない言い回し
FORBIDDEN_WORDS = ("MUST", "必ず", "禁止")
# 文書の MCP の instructions の字数の上限
INSTRUCTIONS_MAX_CHARS = 4096


def _prompt(prompt_id: str, **overrides: Any) -> dict[str, Any]:
    """検査を通る最小のプロンプトの値を返す。"""
    value: dict[str, Any] = {
        "id": prompt_id,
        "name": f"{prompt_id} の名前",
        "description": f"{prompt_id} の説明",
        "kind": "tool",
        "lang": "ja",
        "parts": [{"id": "body", "texts": [{"lang": "ja", "text": "本文"}]}],
    }
    value.update(overrides)
    return value


def _write(directory: Path, relative: str, value: dict[str, Any] | str) -> Path:
    """プロンプトの YAML を書く（JSON は YAML として解析できる）。"""
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return path


def test_prompt_set_render(tmp_path: Path) -> None:
    """when が偽の部品を飛ばしてつなぐ（正常系）。"""
    # 準備
    _write(
        tmp_path,
        "p.yaml",
        _prompt(
            "p",
            vars={
                "name": {"type": "string", "description": "名前", "example": "x"},
                "flag": {"type": "boolean", "description": "旗", "example": True},
            },
            parts=[
                {"id": "a", "texts": [{"lang": "ja", "text": "{{ name }}\n"}]},
                {"id": "b", "when": "{{ flag }}", "texts": [{"lang": "ja", "text": "b\n"}]},
            ],
        ),
    )
    prompts = load_prompts(tmp_path, required=["p"])
    # 実行
    result = prompts.render("p", {"name": "x", "flag": False})
    # 検証
    assert result == "x"


def test_prompt_set_render_when_lang_missing(tmp_path: Path) -> None:
    """注入する言語の本文が無い部品を飛ばす（正常系）。"""
    # 準備
    _write(
        tmp_path,
        "p.yaml",
        _prompt(
            "p",
            parts=[
                {"id": "a", "texts": [{"lang": "ja", "text": "a の本文\n"}]},
                {"id": "b", "texts": [{"lang": "en", "text": "b body\n"}]},
            ],
        ),
    )
    prompts = load_prompts(tmp_path, required=["p"])
    # 実行
    result = prompts.render("p")
    # 検証
    assert result == "a の本文"


def test_prompts_dir() -> None:
    """既定の配置先（正常系）。"""
    # 準備
    env: dict[str, str] = {}
    # 実行
    result = prompts_dir(env)
    # 検証
    assert result == DEFAULT_PROMPTS_DIR


def test_prompts_dir_when_env(tmp_path: Path) -> None:
    """環境変数で差し替える（正常系）。"""
    # 準備
    env = {"PROJECT_INDEX_PROMPTS_DIR": str(tmp_path)}
    # 実行
    result = prompts_dir(env)
    # 検証
    assert result == tmp_path.resolve()


def test_load_prompts(tmp_path: Path) -> None:
    """サブフォルダも含めて読む（正常系）。"""
    # 準備
    _write(tmp_path, "a.yaml", _prompt("a"))
    _write(tmp_path, "mcp/b.yaml", _prompt("mcp/b"))
    # 実行
    result = load_prompts(tmp_path, required=["a", "mcp/b"])
    # 検証
    assert set(result.prompts) == {"a", "mcp/b"}


def test_load_prompts_when_schema_violation(tmp_path: Path) -> None:
    """必須のキーが無い（異常系）。"""
    # 準備
    broken = _prompt("a")
    del broken["kind"]
    a_path = _write(tmp_path, "a.yaml", broken)
    _write(tmp_path, "b.yaml", _prompt("b"))
    # 実行
    with pytest.raises(PromptInvalidError) as exc_info:
        load_prompts(tmp_path, required=["a", "b"])
    # 検証
    problems = exc_info.value.problems
    assert len(problems) == 1
    assert problems[0].file == a_path
    assert "kind" in problems[0].reason


def test_load_prompts_when_many_violations(tmp_path: Path) -> None:
    """全てのファイルの違反を集める（異常系）。"""
    # 準備
    a_path = _write(tmp_path, "a.yaml", "id: a\nname: [\n")
    b_path = _write(tmp_path, "b.yaml", _prompt("b", parts="本文"))
    # 実行
    with pytest.raises(PromptInvalidError) as exc_info:
        load_prompts(tmp_path, required=["a", "b"])
    # 検証
    problems = exc_info.value.problems
    assert [(problem.file, problem.path) for problem in problems] == [
        (a_path, "$"),
        (b_path, "parts"),
    ]


def test_load_prompts_when_id_mismatch(tmp_path: Path) -> None:
    """id がファイルのパスと違う（異常系）。"""
    # 準備
    _write(tmp_path, "a.yaml", _prompt("b"))
    # 実行
    with pytest.raises(PromptInvalidError) as exc_info:
        load_prompts(tmp_path, required=[])
    # 検証
    problems = exc_info.value.problems
    assert len(problems) == 1
    assert problems[0].path == "id"
    assert "a" in problems[0].reason


def test_load_prompts_when_syntax_error(tmp_path: Path) -> None:
    """Jinja2 として解釈できない本文（異常系）。"""
    # 準備
    _write(
        tmp_path,
        "a.yaml",
        _prompt(
            "a",
            vars={"x": {"type": "boolean", "description": "旗", "example": True}},
            parts=[{"id": "p", "texts": [{"lang": "ja", "text": "{% if x %}本文"}]}],
        ),
    )
    # 実行
    with pytest.raises(PromptInvalidError) as exc_info:
        load_prompts(tmp_path, required=["a"])
    # 検証
    problems = exc_info.value.problems
    assert [problem.path for problem in problems] == ["parts[p].texts[ja]"]


def test_load_prompts_when_undefined_variable(tmp_path: Path) -> None:
    """vars に無い変数を使う（異常系）。"""
    # 準備
    _write(
        tmp_path,
        "a.yaml",
        _prompt("a", parts=[{"id": "p", "texts": [{"lang": "ja", "text": "{{ missing }}"}]}]),
    )
    # 実行
    with pytest.raises(PromptInvalidError) as exc_info:
        load_prompts(tmp_path, required=["a"])
    # 検証
    problems = exc_info.value.problems
    assert len(problems) == 1
    assert problems[0].path == "parts"
    assert "missing" in problems[0].reason


def test_load_prompts_when_required_missing(tmp_path: Path) -> None:
    """要るファイルが無い（異常系）。"""
    # 準備
    required = ["mcp/docs/instructions"]
    # 実行
    with pytest.raises(PromptInvalidError) as exc_info:
        load_prompts(tmp_path, required=required)
    # 検証
    problems = exc_info.value.problems
    assert [(problem.file, problem.path) for problem in problems] == [
        (tmp_path / "mcp/docs/instructions.yaml", "$")
    ]


def test_load_prompts_when_bundled() -> None:
    """同梱した YAML が読め、言い回しと字数を守る（正常系）。"""
    # 準備
    required = mcp_prompt_ids()
    # 実行
    result = load_prompts(DEFAULT_PROMPTS_DIR, required=required)
    # 検証
    texts = [
        text.text
        for loaded in result.prompts.values()
        for part in loaded.doc.parts
        for text in part.texts
    ]
    assert [text for text in texts if any(word in text for word in FORBIDDEN_WORDS)] == []
    assert len(result.render(DOCS_INSTRUCTIONS_PROMPT_ID)) <= INSTRUCTIONS_MAX_CHARS

from __future__ import annotations

from project_index.features.outline.code import (
    outline_package_json,
    outline_python,
    outline_script,
)


def test_outline_python() -> None:
    """関数・クラス・import・docstring（正常系）。"""
    # 準備
    text = (
        '"""タスク。\n\n保存を受け持つ。\n"""\n'
        "import yaml\n"
        "from .a import b\n"
        "\n"
        "\n"
        "def f():\n"
        "    return 1\n"
        "\n"
        "\n"
        "async def g():\n"
        "    return 2\n"
        "\n"
        "\n"
        "class C:\n"
        "    def m(self):\n"
        "        return 3\n"
    )
    # 実行
    result = outline_python(text)
    # 検証
    assert result.functions == ("f", "g")
    assert result.classes == ("C",)
    assert result.imports == ("yaml", ".a")
    assert result.existing_description is not None
    assert result.existing_description.source == "docstring"
    assert result.existing_description.title == "タスク。"
    assert result.existing_description.description == "保存を受け持つ。"


def test_outline_python_when_syntax_error() -> None:
    """読めないソース（正常系）。"""
    # 実行
    result = outline_python("def (:")
    # 検証
    assert result.functions == ()
    assert result.classes == ()
    assert result.imports == ()
    assert result.existing_description is None


def test_outline_script() -> None:
    """関数・クラス・import・先頭の説明（正常系）。"""
    # 準備
    text = (
        "/** 画面の部品。 */\n"
        "import React from 'react'\n"
        "\n"
        "export function A() {\n"
        "  function inner() {}\n"
        "  return inner\n"
        "}\n"
        "\n"
        "const b = () => 1\n"
        "\n"
        "export default class C {}\n"
    )
    # 実行
    result = outline_script(text)
    # 検証
    assert result.functions == ("A", "b")
    assert result.classes == ("C",)
    assert result.imports == ("react",)
    assert result.existing_description is not None
    assert result.existing_description.title == "画面の部品。"


def test_outline_package_json() -> None:
    """description を持つ（正常系）。"""
    # 実行
    result = outline_package_json('{"name": "lint", "description": "文書の検査"}')
    # 検証
    assert result.existing_description is not None
    assert result.existing_description.source == "package_json"
    assert result.existing_description.title == "lint"
    assert result.existing_description.description == "文書の検査"


def test_outline_package_json_when_no_description() -> None:
    """description が無い（正常系）。"""
    # 実行
    result = outline_package_json('{"name": "lint"}')
    # 検証
    assert result.existing_description is None

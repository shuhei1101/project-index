from __future__ import annotations

import pytest
from ruamel.yaml.comments import CommentedMap

from project_index.shared.yaml_io import (
    YamlLoadError,
    dump_roundtrip,
    load_roundtrip,
    load_yaml,
)


def test_load_yaml() -> None:
    """素の値で読む（正常系）。"""
    # 準備
    text = "a: [1, 2]\n"
    # 実行
    result = load_yaml(text)
    # 検証
    assert result == {"a": [1, 2]}


def test_load_yaml_when_syntax_error() -> None:
    """構文の誤り（異常系）。"""
    # 準備
    text = "a: [1, 2\n"
    # 実行・検証
    with pytest.raises(YamlLoadError) as exc_info:
        load_yaml(text, file="x.yaml")
    assert exc_info.value.file == "x.yaml"
    assert exc_info.value.line == 1


def test_load_yaml_when_duplicate_key() -> None:
    """キーの重複（異常系）。"""
    # 準備
    text = "a: 1\na: 2\n"
    # 実行・検証
    with pytest.raises(YamlLoadError) as exc_info:
        load_yaml(text)
    assert "a" in exc_info.value.reason


def test_load_roundtrip() -> None:
    """コメントを保つ（正常系）。"""
    # 準備
    text = "# c\na: 1  # x\n"
    # 実行
    result = dump_roundtrip(load_roundtrip(text))
    # 検証
    assert result == "# c\na: 1  # x\n"


def test_load_roundtrip_when_quotes() -> None:
    """引用符の種類を保つ（正常系）。"""
    # 準備
    doc = load_roundtrip("version: '2020-12'\ntitle: \"A: b\"\nname: x\n")
    doc["name"] = "y"
    # 実行
    result = dump_roundtrip(doc)
    # 検証
    assert result == "version: '2020-12'\ntitle: \"A: b\"\nname: y\n"


def test_load_roundtrip_when_not_mapping() -> None:
    """最上位が配列（異常系）。"""
    # 準備
    text = "- 1\n"
    # 実行・検証
    with pytest.raises(YamlLoadError):
        load_roundtrip(text)


def test_dump_roundtrip() -> None:
    """改行を含む値をリテラルにする（正常系）。"""
    # 準備
    doc = CommentedMap({"a": "x\ny"})
    # 実行
    result = dump_roundtrip(doc)
    # 検証
    assert result == "a: |-\n  x\n  y\n"

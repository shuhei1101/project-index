from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.parser import Parser

from project_index.shared import yaml_io as yaml_io_module
from project_index.shared.yaml_io import (
    YamlLoadError,
    c_loader_available,
    dump_roundtrip,
    load_roundtrip,
    load_yaml,
)

if TYPE_CHECKING:
    from collections.abc import Callable


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


def test_dump_roundtrip_when_original_unindented() -> None:
    """字下げ無しの配列を保つ（正常系）。"""
    # 準備
    original = "items:\n- key: k1\n  label: a\n"
    doc = load_roundtrip(original)
    doc["items"].append(CommentedMap({"key": "k2", "label": "b"}))
    # 実行
    result = dump_roundtrip(doc, original=original)
    # 検証
    assert result == "items:\n- key: k1\n  label: a\n- key: k2\n  label: b\n"


def test_dump_roundtrip_when_original_indented() -> None:
    """2 文字の字下げの配列を保つ（正常系）。"""
    # 準備
    original = "items:\n  - key: k1\n    label: a\n"
    doc = load_roundtrip(original)
    doc["items"].append(CommentedMap({"key": "k2", "label": "b"}))
    # 実行
    result = dump_roundtrip(doc, original=original)
    # 検証
    assert result == "items:\n  - key: k1\n    label: a\n  - key: k2\n    label: b\n"


def test_dump_roundtrip_when_original_without_sequence() -> None:
    """配列の無い元の文字列は既定の字下げ（正常系）。"""
    # 準備
    original = "a: 1\n"
    doc = load_roundtrip(original)
    doc["items"] = [CommentedMap({"key": "k1", "label": "a"})]
    # 実行
    result = dump_roundtrip(doc, original=original)
    # 検証
    assert result == "a: 1\nitems:\n  - key: k1\n    label: a\n"


def test_load_yaml_when_unreadable_by_c() -> None:
    """C の解析で読めない YAML を Python 実装で読み直す（正常系）。"""
    # 準備
    text = "tags: [scope:a, topic:b]\n"
    # 実行
    result = load_yaml(text)
    # 検証
    assert result == {"tags": ["scope:a", "topic:b"]}


@pytest.mark.skipif(not c_loader_available(), reason="C の解析を使用できない環境")
def test_load_yaml_when_c(monkeypatch: pytest.MonkeyPatch) -> None:
    """C の解析で読む（正常系）。"""
    # 準備
    calls: list[str] = []
    real: Callable[..., None] = vars(Parser)["__init__"]

    def counting(self: Parser, *args: Any, **kwargs: Any) -> None:
        calls.append("parser")
        real(self, *args, **kwargs)

    monkeypatch.setattr(Parser, "__init__", counting)
    # 実行
    result = load_yaml("a: [1, 2]\n")
    # 検証
    assert result == {"a": [1, 2]}
    assert calls == []


def test_c_loader_available() -> None:
    """依存を入れた環境では使用できる（正常系）。"""
    # 実行
    result = yaml_io_module.c_loader_available()
    # 検証
    assert result is True

from __future__ import annotations

from project_index.features.write.replace import replace_in_values

from project_index.shared.yaml_io import load_roundtrip

CONTENT = "description: 旧語\nitems:\n  - text: 旧語と旧語\nnotes:\n  旧語: 旧語\ncount: 3\n"


def test_replace_in_values() -> None:
    """配下の文字列を置換し、キーは変えない（正常系）。"""
    # 準備
    content = load_roundtrip(CONTENT)
    # 実行
    count = replace_in_values(content, old="旧語", new="新語", fields=None, skip=["id"])
    # 検証
    assert content["description"] == "新語"
    assert content["items"][0]["text"] == "新語と新語"
    assert dict(content["notes"]) == {"旧語": "新語"}
    assert content["count"] == 3
    assert count == 4


def test_replace_in_values_when_fields() -> None:
    """項目を絞る（正常系）。"""
    # 準備
    content = load_roundtrip(CONTENT)
    # 実行
    count = replace_in_values(content, old="旧語", new="新語", fields=["items"], skip=["id"])
    # 検証
    assert content["items"][0]["text"] == "新語と新語"
    assert content["description"] == "旧語"
    assert dict(content["notes"]) == {"旧語": "旧語"}
    assert count == 2


def test_replace_in_values_when_skipped() -> None:
    """ID の列と body_file の列は置換しない（正常系）。"""
    # 準備
    content = load_roundtrip("id: 旧語-1\npath: 旧語.md\nname: 旧語\n")
    # 実行
    count = replace_in_values(content, old="旧語", new="新語", fields=None, skip=["id", "path"])
    # 検証
    assert content["id"] == "旧語-1"
    assert content["path"] == "旧語.md"
    assert content["name"] == "新語"
    assert count == 1

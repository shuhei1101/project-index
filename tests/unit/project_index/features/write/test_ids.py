from __future__ import annotations

from project_index.features.write.ids import generate_id


def test_generate_id() -> None:
    """slug と重なり（正常系）。"""
    # 実行
    result = generate_id(
        "{kind}-{slug}",
        kind="sample",
        data={"name": "Doc Three!"},
        existing=["sample-doc-three"],
    )
    # 検証
    assert result == "sample-doc-three-2"


def test_generate_id_when_no_ascii() -> None:
    """slug を作れない（正常系）。"""
    # 実行
    result = generate_id("{kind}-{slug}", kind="sample", data={"name": "文書"}, existing=[])
    # 検証
    assert result == "sample-doc"

from __future__ import annotations

import pytest
from project_index.features.validation.scripts import parse_validator_output


def test_parse_validator_output() -> None:
    """違反の配列（正常系）。"""
    # 準備
    stdout = '[{"path": "links[0]", "rule": "無いリンク先", "fix": "x"}, "本文が空"]'
    # 実行
    result = parse_validator_output(stdout, validator_id="check-links")
    # 検証
    assert [violation.rule for violation in result] == [
        "check-links: 無いリンク先",
        "check-links: 本文が空",
    ]
    assert result[1].path == "$"


@pytest.mark.parametrize("stdout", ["", "[]\n"])
def test_parse_validator_output_when_empty(stdout: str) -> None:
    """合格（正常系）。"""
    # 実行
    result = parse_validator_output(stdout, validator_id="check-links")
    # 検証
    assert result == []


def test_parse_validator_output_when_invalid() -> None:
    """JSON でない出力（正常系）。"""
    # 実行
    result = parse_validator_output("ok", validator_id="check-links")
    # 検証
    assert len(result) == 1
    assert "配列の JSON ではありません" in result[0].rule

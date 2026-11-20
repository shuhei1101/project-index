from __future__ import annotations

import time

import pytest

from project_index.features.write.secrets import SecretFinding, scan_text, secret_findings

# 秘密の値の書式の見本は、テストのファイルにトークンの形のまま記載しないため、部品をつないで組み立てる
GITHUB_TOKEN = "gh" + "p_" + "A1b2C3d4" * 4 + "E5f6"
AWS_KEY = "AK" + "IA" + "QWERTYUIOP234567"
SLACK_TOKEN = "xo" + "xb-" + "1234567890-abcdefghij"
OPENAI_KEY = "sk-" + "proj-" + "a1B2c3D4" * 3
ANTHROPIC_KEY = "sk-" + "ant-api03-" + "a" * 93 + "AA"
PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----"
EMAIL = "user" + "@" + "example.com"
# 書き込みの期限（NFR-11 の 32 秒）の 10%
LONG_INPUT_LIMIT_SEC = 3.2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(f"token: {GITHUB_TOKEN}", ["github-token"], id="github-token"),
        pytest.param(f"key: {AWS_KEY}", ["aws-access-key"], id="aws-access-key"),
        pytest.param(f"slack: {SLACK_TOKEN}", ["slack-token"], id="slack-token"),
        pytest.param(f"openai: {OPENAI_KEY}", ["openai-api-key"], id="openai-api-key"),
        pytest.param(f"anthropic: {ANTHROPIC_KEY}", ["anthropic-api-key"], id="anthropic-api-key"),
        pytest.param(PRIVATE_KEY, ["private-key"], id="private-key"),
        pytest.param(f"連絡先は {EMAIL} です", ["email-address"], id="email-address"),
    ],
)
def test_scan_text(text: str, expected: list[str]) -> None:
    """種類ごとに該当する（正常系）。"""
    # 実行
    result = scan_text(text)
    # 検証
    assert result == expected


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("commit: e5b27f3a9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f", id="sha"),
        pytest.param("docs/module/MOD-178.py.yaml", id="path"),
        pytest.param("https://example.com/a/b?c=d", id="url"),
        pytest.param("ghp_short", id="short-github-prefix"),
    ],
)
def test_scan_text_when_not_secret(text: str) -> None:
    """該当しない（正常系）。"""
    # 実行
    result = scan_text(text)
    # 検証
    assert result == []


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("a" * 1_000_000, id="alnum"),
        pytest.param("@." * 500_000, id="at-dot"),
        pytest.param("-----BEGIN" * 100_000, id="begin"),
    ],
)
def test_scan_text_when_long_input(text: str) -> None:
    """長い入力でも期限の内に終わる（正常系）。"""
    # 準備
    started = time.monotonic()
    # 実行
    result = scan_text(text)
    elapsed = time.monotonic() - started
    # 検証
    assert result == []
    assert elapsed < LONG_INPUT_LIMIT_SEC


def test_secret_findings() -> None:
    """変えた項目だけ（正常系）。"""
    # 準備
    before = {"id": "n1", "notes": f"連絡先 {EMAIL}", "description": "説明"}
    after = {"id": "n1", "notes": f"連絡先 {EMAIL}", "description": f"説明 {GITHUB_TOKEN}"}
    # 実行
    result = secret_findings(before, after)
    # 検証
    assert result == [SecretFinding(path="description", kind="github-token")]
    assert GITHUB_TOKEN not in repr(result)


def test_secret_findings_when_body() -> None:
    """本文の追加の行（正常系）。"""
    # 準備
    data = {"id": "n1", "path": "n1.md"}
    body_before = "# 見出し\n本文\n"
    body_after = f"# 見出し\n本文\n{PRIVATE_KEY}\n"
    # 実行
    result = secret_findings(data, data, body_before=body_before, body_after=body_after)
    # 検証
    assert result == [SecretFinding(path="@body", kind="private-key")]

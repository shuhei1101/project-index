from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

DECISIONS = "decisions:\n  folders: [tmp/a, tmp/b]\n"


def _decision_files(
    sample_file_set: Callable[..., dict[str, str]], sample_config_text: Callable[..., str]
) -> dict[str, str]:
    """D-1 を 1 つ目のフォルダにだけ、D-2 を 2 つのフォルダに置いた配信元のファイル一式を返す。"""
    return sample_file_set(
        **{
            "project-index.yaml": sample_config_text(DECISIONS),
            "tmp/a/.mindstella/docs/D-1.md": "# D-1\n\n**太字**のまま\n",
            "tmp/a/.mindstella/docs/D-2.md": "# D-2\n",
            "tmp/b/.mindstella/docs/D-2.md": "# D-2 の別の版\n",
        }
    )


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """ちょうど 1 つのフォルダにある検討事項の文書の本文を返す（正常系）。"""
    # 準備
    env = make_server(make_source("sample", _decision_files(sample_file_set, sample_config_text)))
    # 実行
    response = env.client.get("/sources/sample/decisions/D-1")
    # 検証
    assert response.status_code == 200
    assert response.json() == {
        "id": "D-1",
        "folder": "tmp/a",
        "body": "# D-1\n\n**太字**のまま\n",
    }


def test_error_when_not_unique(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """当たるフォルダが 0 個か 2 個以上の ID を断る（異常系）。"""
    # 準備
    env = make_server(make_source("sample", _decision_files(sample_file_set, sample_config_text)))
    # 実行
    ambiguous = env.client.get("/sources/sample/decisions/D-2")
    missing = env.client.get("/sources/sample/decisions/D-3")
    # 検証
    assert ambiguous.status_code == 404
    assert ambiguous.json()["missing"] == "doc"
    assert ambiguous.json()["reason"] == "ambiguous"
    assert ambiguous.json()["folders"] == ["tmp/a", "tmp/b"]
    assert missing.status_code == 404
    assert missing.json()["missing"] == "doc"
    assert missing.json()["reason"] == "not_found"


def test_error_when_id_invalid(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """フォルダの外を指す ID を形式で断る（異常系）。"""
    # 準備
    files = _decision_files(sample_file_set, sample_config_text)
    files["tmp/a/.mindstella/secret.md"] = "秘密\n"
    env = make_server(make_source("sample", files))
    # 実行
    response = env.client.get("/sources/sample/decisions/..%2Fsecret")
    # 検証
    assert response.status_code == 404
    assert "秘密" not in response.text

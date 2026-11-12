from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

DECISIONS = "decisions:\n  folders: [tmp/a, tmp/b]\n"


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """decisions.folders にある検討事項の ID と、ID ごとに当たるフォルダの数を返す（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(DECISIONS),
            "tmp/a/.mindstella/docs/D-1.md": "# D-1\n",
            "tmp/a/.mindstella/docs/D-2.md": "# D-2\n",
            "tmp/b/.mindstella/docs/D-2.md": "# D-2 の別の版\n",
        }
    )
    env = make_server(make_source("sample", files))
    # 実行
    response = env.client.get("/sources/sample/decisions")
    # 検証
    assert response.status_code == 200
    assert response.json()["decisions"] == [
        {"id": "D-1", "folders": 1},
        {"id": "D-2", "folders": 2},
    ]


def test_normal_when_no_decision_folder(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """decisions.folders を持たない配信元は空の一覧を返す（正常系）。"""
    # 準備
    env = make_server(make_source("plain"))
    # 実行
    response = env.client.get("/sources/plain/decisions")
    # 検証
    assert response.status_code == 200
    assert response.json()["decisions"] == []


def test_error_when_source_not_found(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """無い配信元を断る（異常系）。"""
    # 準備
    env = make_server(make_source("sample"))
    # 実行
    response = env.client.get("/sources/unknown/decisions")
    # 検証
    assert response.status_code == 404
    assert response.json()["missing"] == "source"

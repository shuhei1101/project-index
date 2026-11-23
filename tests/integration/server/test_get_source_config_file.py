from __future__ import annotations

from typing import TYPE_CHECKING, Any

from project_index.shared.hashing import content_hash
from tests.integration.server.conftest import direct_commit_config

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.integration.server.conftest import DirectCommitSource

URL = "/sources/sample/config/file"
# コメントを含み、配信元の設定の直コミットを許可した配信元の設定
SOURCE_CONFIG = "# 配信元の設定\n" + direct_commit_config().replace(
    "  kinds: [note]\n",
    "  kinds: [note]  # 書き込みの API から直コミットする種類\n  config: true\n",
)


def test_normal(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
) -> None:
    """重ねる前の project-index.yaml の内容とバージョンを返却する（正常系）。"""
    # 準備
    direct = make_direct_commit_source(config=SOURCE_CONFIG, write_api_config=True)
    env = make_server(direct.spec)
    # 実行
    response = env.client.get(URL)
    again = env.client.get(URL)
    (direct.develop / "project-index.yaml").write_text(
        SOURCE_CONFIG + "description: 後の説明\n", encoding="utf-8"
    )
    changed = env.client.get(URL)
    # 検証
    data = response.json()
    assert response.status_code == 200, data
    assert (
        data["content"].encode("utf-8")
        == (direct.develop / "project-index.yaml").read_bytes()[
            : len(SOURCE_CONFIG.encode("utf-8"))
        ]
    )
    assert data["content"] == SOURCE_CONFIG
    assert data["version"] == content_hash(SOURCE_CONFIG)
    assert data["branch"] == "develop"
    assert data["protectedKeys"] == [
        "validators",
        "converters",
        "generators",
        "direct_commit",
        "worktrees",
    ]
    assert again.json()["version"] == data["version"]
    assert changed.json()["version"] != data["version"]


def test_error_when_not_allowed(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
) -> None:
    """配信元の設定の直コミットを許可していない配信元には内容を返却しない（異常系）。"""
    # 準備
    direct = make_direct_commit_source(config=SOURCE_CONFIG)
    env = make_server(direct.spec)
    # 実行
    response = env.client.get(URL)
    # 検証
    data = response.json()
    assert response.status_code == 403, data
    assert "sources[].direct_commit.write_api_config" in " ".join(data["nextSteps"])
    assert "content" not in data


def test_error_when_split(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    tmp_path: Path,
) -> None:
    """端末の設定の config が project-index.yaml 1 つでない配信元は断る（異常系）。"""
    # 準備
    direct = make_direct_commit_source(config=SOURCE_CONFIG, write_api_config=True)
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("description: 重ねる説明\n", encoding="utf-8")
    direct.spec.config = [direct.folder / "project-index.yaml", overlay]
    env = make_server(direct.spec)
    # 実行
    response = env.client.get(URL)
    # 検証
    data = response.json()
    assert response.status_code == 409, data
    assert data["files"] == [str(direct.folder / "project-index.yaml"), str(overlay)]


def test_error_when_source_not_found(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
) -> None:
    """無い配信元・配信していない配信元を断る（異常系）。"""
    # 準備
    direct = make_direct_commit_source(config=SOURCE_CONFIG, write_api_config=True)
    env = make_server(direct.spec)
    # 実行
    response = env.client.get("/sources/unknown/config/file")
    # 検証
    data = response.json()
    assert response.status_code == 404, data
    assert data["missing"] == "source"

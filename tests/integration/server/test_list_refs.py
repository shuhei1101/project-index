from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """ブランチ・タグ・最近の commit を返す（正常系）。"""
    # 準備
    source = make_source("sample")
    commit_all(source.folder, {"docs/doc-1.yaml": "id: doc-1\nname: 新しい名前\n"}, "docs: 改名")
    run_git(source.folder, "tag", "v0.1.0")
    add_worktree(source.folder, "x")
    env = make_server(source)
    # 実行
    response = env.client.get("/sources/sample/refs")
    # 検証
    body = response.json()
    assert response.status_code == 200
    assert body["git"] is True
    assert body["defaultRef"] == "develop"
    assert {branch["name"] for branch in body["branches"]} >= {"develop", "feat/x"}
    assert [tag["name"] for tag in body["tags"]] == ["v0.1.0"]
    assert [commit["subject"] for commit in body["commits"]] == ["docs: 改名", "init"]


def test_normal_when_non_git_source(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """Git 管理外の配信元は git: false を返す（正常系）。"""
    # 準備
    env = make_server(make_source("notes", git=False))
    # 実行
    response = env.client.get("/sources/notes/refs")
    # 検証
    body = response.json()
    assert response.status_code == 200
    assert body["git"] is False
    assert body["branches"] == []
    assert body["tags"] == []
    assert body["commits"] == []


def test_error_when_source_not_found(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """無い配信元を断る（異常系）。"""
    # 準備
    env = make_server(make_source("sample"))
    # 実行
    response = env.client.get("/sources/unknown/refs")
    # 検証
    body = response.json()
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "unknown" in body["detail"]

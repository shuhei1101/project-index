from __future__ import annotations

from typing import TYPE_CHECKING, Any

from project_index.shared.hashing import content_hash

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.integration.server.conftest import DirectCommitSource

URL = "/sources/sample/commits"
NOTES = {"notes/n1.yaml": "id: n1\nname: メモ 1\n", "notes/n2.yaml": "id: n2\nname: メモ 2\n"}


def _version(path: Path) -> str:
    """ファイルの今のバージョンを返す。"""
    return content_hash(path.read_text(encoding="utf-8"))


def _body(direct: DirectCommitSource, **extra: Any) -> dict[str, Any]:
    """n1 の説明の更新と n2 の削除を 1 回で送る本文を作る。"""
    notes = direct.develop / "notes"
    return {
        "writes": [
            {
                "op": "update",
                "id": "n1",
                "expected_version": _version(notes / "n1.yaml"),
                "set": {"description": "新しい説明"},
            }
        ],
        "deletes": [{"id": "n2", "expectedVersion": _version(notes / "n2.yaml")}],
        "message": "docs: note を更新する",
        **extra,
    }


def _git_state(direct: DirectCommitSource, run_git: Callable[..., str]) -> tuple[str, str, str]:
    """リモートの develop・develop のワークツリーの HEAD・git status の組を返す。"""
    return (
        run_git(direct.bare, "rev-parse", "develop").strip(),
        run_git(direct.develop, "rev-parse", "HEAD").strip(),
        run_git(direct.develop, "status", "--porcelain").strip(),
    )


def test_normal(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """書き込みと削除を 1 つのコミットにまとめてプッシュする（正常系）。"""
    # 準備
    direct = make_direct_commit_source(files=NOTES, write_api_kinds=["note"])
    env = make_server(direct.spec)
    remote_before = run_git(direct.bare, "rev-parse", "develop").strip()
    # 実行
    response = env.client.post(URL, json=_body(direct))
    # 検証
    data = response.json()
    remote_after = run_git(direct.bare, "rev-parse", "develop").strip()
    changed = run_git(direct.bare, "show", "--name-only", "--format=%s", remote_after).split("\n")
    assert response.status_code == 200, data
    assert data["applied"] is True
    assert [(item["kind"], item["id"], item["status"]) for item in data["results"]] == [
        ("write", "n1", "updated"),
        ("delete", "n2", "deleted"),
    ]
    assert data["commit"]["sha"] == remote_after
    assert run_git(direct.bare, "rev-parse", f"{remote_after}~1").strip() == remote_before
    assert changed[0] == "docs: note を更新する"
    assert sorted(line for line in changed[1:] if line) == [
        "generated/notes.txt",
        "notes/n1.yaml",
        "notes/n2.yaml",
    ]
    assert run_git(direct.develop, "status", "--porcelain").strip() == ""


def test_normal_when_dry_run(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """dryRun は検査と差分だけを返却する（正常系）。"""
    # 準備
    direct = make_direct_commit_source(files=NOTES, write_api_kinds=["note"])
    env = make_server(direct.spec)
    before = _git_state(direct, run_git)
    # 実行
    response = env.client.post(URL, json=_body(direct, dryRun=True))
    # 検証
    data = response.json()
    assert response.status_code == 200, data
    assert data["applied"] is False
    assert data["commit"] is None
    assert data["results"][0]["diff"]
    assert _git_state(direct, run_git) == before
    assert (direct.develop / "notes" / "n2.yaml").exists()


def test_error_when_write_api_not_allowed(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """write_api_kinds に無い種類は断る（異常系）。"""
    # 準備
    direct = make_direct_commit_source(files=NOTES)
    env = make_server(direct.spec)
    before = _git_state(direct, run_git)
    # 実行
    response = env.client.post(URL, json=_body(direct))
    # 検証
    data = response.json()
    assert response.status_code == 403, data
    assert data["kinds"] == ["note"]
    assert "sources[].direct_commit.write_api_kinds" in " ".join(data["nextSteps"])
    assert _git_state(direct, run_git) == before


def test_error_when_disallowed_kind_rewritten(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """参照を除いて書き換わる文書に直コミットを許可していない種類がある（異常系）。"""
    # 準備
    rule = "id: r1\nname: 規約 1\nrelated:\n  - to: n2\n    type: references\n"
    direct = make_direct_commit_source(
        files={**NOTES, "rules/r1.yaml": rule}, write_api_kinds=["note"]
    )
    env = make_server(direct.spec)
    before = _git_state(direct, run_git)
    body = {
        "deletes": [{"id": "n2", "expectedVersion": _version(direct.develop / "notes/n2.yaml")}],
        "onReferenced": "unlink",
        "message": "docs: note を消す",
    }
    # 実行
    response = env.client.post(URL, json=body)
    # 検証
    data = response.json()
    assert response.status_code == 422, data
    assert any(
        item["path"].startswith("deletes[0]")
        and "rule は直コミットを許可していない" in item["reason"]
        for item in data["errors"]
    )
    assert _git_state(direct, run_git) == before
    assert (direct.develop / "rules" / "r1.yaml").read_text(encoding="utf-8") == rule
    assert (direct.develop / "notes" / "n2.yaml").exists()


def test_error_when_validation_failed(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """1 つでも違反があればどれも書き込まない（異常系）。"""
    # 準備
    direct = make_direct_commit_source(files=NOTES, write_api_kinds=["note"])
    env = make_server(direct.spec)
    before = _git_state(direct, run_git)
    notes = direct.develop / "notes"
    body = {
        "writes": [
            {
                "op": "update",
                "id": "n1",
                "expected_version": _version(notes / "n1.yaml"),
                "set": {"description": "新しい説明"},
            },
            {
                "op": "update",
                "id": "n2",
                "expected_version": _version(notes / "n2.yaml"),
                "set": {"name": 1},
            },
        ],
        "message": "docs: note を更新する",
    }
    # 実行
    response = env.client.post(URL, json=body)
    # 検証
    data = response.json()
    assert response.status_code == 422, data
    assert [item["path"] for item in data["errors"] if item["path"].startswith("writes[1]")]
    assert not [item for item in data["errors"] if item["path"].startswith("writes[0]")]
    assert _git_state(direct, run_git) == before
    assert (notes / "n1.yaml").read_text(encoding="utf-8") == NOTES["notes/n1.yaml"]


def test_error_when_version_conflict(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
    push_from_other_clone: Callable[..., str],
) -> None:
    """取り込んだ後のバージョンと照合する（異常系）。"""
    # 準備
    direct = make_direct_commit_source(files=NOTES, write_api_kinds=["note"])
    env = make_server(direct.spec)
    body = _body(direct)
    other = push_from_other_clone(
        direct.bare, {"notes/n1.yaml": "id: n1\nname: 先に書き換えたメモ\n"}
    )
    # 実行
    response = env.client.post(URL, json=body)
    # 検証
    data = response.json()
    assert response.status_code == 409, data
    assert "n1" in data["detail"]
    assert data["current"] == content_hash("id: n1\nname: 先に書き換えたメモ\n")
    assert run_git(direct.bare, "rev-parse", "develop").strip() == other
    assert (direct.develop / "notes" / "n2.yaml").exists()


def test_error_when_cross_origin(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """ブラウザの別のオリジンからの要求は断る（異常系）。"""
    # 準備
    direct = make_direct_commit_source(files=NOTES, write_api_kinds=["note"])
    env = make_server(direct.spec)
    before = _git_state(direct, run_git)
    # 実行
    response = env.client.post(URL, json=_body(direct), headers={"Origin": "http://127.0.0.1:9999"})
    # 検証
    assert response.status_code == 403
    assert "CrossOriginError" in response.text
    assert _git_state(direct, run_git) == before


def test_error_when_source_not_found(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
) -> None:
    """配信していない配信元は断る（異常系）。"""
    # 準備
    direct = make_direct_commit_source(files=NOTES, write_api_kinds=["note"])
    env = make_server(direct.spec)
    # 実行
    response = env.client.post(
        "/sources/missing/commits",
        json={"deletes": [{"id": "n2", "expectedVersion": "0"}], "message": "m"},
    )
    # 検証
    assert response.status_code == 404
    assert "missing" in response.text


def test_error_when_sqlite_kind_included(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """SQLite の表の行の文書への操作を含む要求を、直コミットを許可していても断る（異常系）。"""
    from tests.integration.server.conftest import (
        NOTES_DB_ROW,
        direct_commit_config,
        write_notes_db,
    )

    # 準備
    config = direct_commit_config(kinds=("note", "notes_db")).replace(
        "generators:\n", NOTES_DB_ROW.format(limit="") + "generators:\n"
    )
    direct = make_direct_commit_source(
        files={**NOTES, ".gitignore": "data/\n"},
        config=config,
        write_api_kinds=["note", "notes_db"],
    )
    db = write_notes_db(
        direct.spec.folder, [("sq1", "ゲーム実況 1", "今日の目標 1", '["game"]', "[]")]
    )
    db_before = db.read_bytes()
    env = make_server(direct.spec)
    before = _git_state(direct, run_git)
    x_before = run_git(direct.x, "status", "--porcelain").strip()
    body = {
        "writes": [
            {
                "op": "update",
                "id": "n1",
                "expected_version": _version(direct.develop / "notes" / "n1.yaml"),
                "set": {"description": "新しい説明"},
            },
            {
                "op": "update",
                "id": "sq1",
                "expected_version": "000000",
                "set": {"title": "書き換え"},
            },
        ],
        "message": "docs: note を更新する",
    }
    # 実行
    response = env.client.post(URL, json=body)
    # 検証
    data = response.json()
    assert response.status_code == 403, data
    assert response.headers["content-type"].startswith("application/problem+json")
    assert [item["path"] for item in data["errors"]] == ["writes[1]"]
    assert "notes_db" in data["errors"][0]["reason"]
    assert _git_state(direct, run_git) == before
    assert run_git(direct.x, "status", "--porcelain").strip() == x_before
    assert db.read_bytes() == db_before

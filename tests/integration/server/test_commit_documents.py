from __future__ import annotations

import sys
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


ENV_DUMP = (
    "import os, sys, pathlib\n"
    "keys = sorted(key for key in os.environ if key.startswith('PROJECT_INDEX_'))\n"
    "text = ''.join(f'{key}={os.environ[key]}\\n' for key in keys)\n"
    "pathlib.Path(sys.argv[1]).write_text(text, encoding='utf-8')\n"
    "print('ran', end='')\n"
)
FAILING = "import sys\nsys.stderr.write('失敗しました\\n')\nsys.exit(1)\n"
N1_CHANGED = "id: n1\nname: ほかの変更\n"


def _conflict_branches(direct: DirectCommitSource, run_git: Callable[..., str]) -> list[str]:
    """クローンにある衝突したときのブランチの名前。"""
    listed = run_git(
        direct.folder, "branch", "--list", "--format=%(refname:short)", "project-index/*"
    )
    return listed.split()


def _worktrees(direct: DirectCommitSource, run_git: Callable[..., str]) -> str:
    """クローンの `git worktree list` の出力。"""
    return run_git(direct.folder, "worktree", "list")


def _conflicting_body(
    direct: DirectCommitSource,
    push_from_other_clone: Callable[..., str],
    run_git: Callable[..., str],
) -> dict[str, Any]:
    """編集を始めたときのコミットを添えた本文を作ってから、ほかの変更で n1 を書き換える。"""
    body = _body(direct, baseCommit=run_git(direct.develop, "rev-parse", "HEAD").strip())
    push_from_other_clone(direct.bare, {"notes/n1.yaml": N1_CHANGED})
    return body


def test_normal_when_conflict_kept_in_branch(
    tmp_path: Path,
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    push_from_other_clone: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """衝突したら修正をブランチに残してスクリプトを実行する（正常系）。"""
    # 準備
    dump = tmp_path / "env.txt"
    direct = make_direct_commit_source(
        files=NOTES,
        write_api_kinds=["note"],
        on_conflict=[sys.executable, "-c", ENV_DUMP, str(dump)],
    )
    env = make_server(direct.spec)
    body = _conflicting_body(direct, push_from_other_clone, run_git)
    remote_before = run_git(direct.bare, "rev-parse", "develop").strip()
    worktrees_before = len(_worktrees(direct, run_git).splitlines())
    # 実行
    response = env.client.post(URL, json=body)
    # 検証
    data = response.json()
    conflict = data["conflict"]
    assert response.status_code == 200, data
    assert data["applied"] is False
    assert data["commit"] is None
    assert conflict["branch"].startswith("project-index/conflict/")
    assert run_git(direct.folder, "rev-parse", conflict["branch"]).strip() == conflict["commit"]
    assert conflict["baseCommit"] == body["baseCommit"]
    assert [item["path"] for item in conflict["errors"]] == ["n1"]
    assert conflict["script"]["exitCode"] == 0
    assert conflict["script"]["stdout"] == "ran"
    branch = conflict["branch"]
    assert run_git(direct.folder, "rev-parse", f"{branch}~1").strip() == body["baseCommit"]
    assert run_git(direct.folder, "log", "-1", "--format=%s", branch).strip() == body["message"]
    changed = run_git(direct.folder, "diff", "--name-only", f"{branch}~1", branch).split()
    assert sorted(changed) == ["generated/notes.txt", "notes/n1.yaml", "notes/n2.yaml"]
    assert run_git(direct.bare, "rev-parse", "develop").strip() == remote_before
    assert run_git(direct.bare, "branch", "--list", "project-index/*").strip() == ""
    assert run_git(direct.develop, "rev-parse", "HEAD").strip() == remote_before
    assert run_git(direct.develop, "status", "--porcelain").strip() == ""
    assert len(_worktrees(direct, run_git).splitlines()) == worktrees_before
    assert list((env.state_dir / "conflicts").iterdir()) == []
    dumped = dump.read_text(encoding="utf-8")
    assert "PROJECT_INDEX_SOURCE=sample\n" in dumped
    assert f"PROJECT_INDEX_CONFLICT_BRANCH={branch}\n" in dumped
    assert f"PROJECT_INDEX_CONFLICT_COMMIT={conflict['commit']}\n" in dumped


def test_normal_when_conflict_without_script(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    push_from_other_clone: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """衝突してスクリプトの指定が無ければブランチだけを残す（正常系）。"""
    # 準備
    direct = make_direct_commit_source(files=NOTES, write_api_kinds=["note"])
    env = make_server(direct.spec)
    body = _conflicting_body(direct, push_from_other_clone, run_git)
    # 実行
    response = env.client.post(URL, json=body)
    # 検証
    data = response.json()
    assert response.status_code == 200, data
    assert data["conflict"]["branch"] is not None
    assert data["conflict"]["commit"] is not None
    assert data["conflict"]["script"] is None
    assert _conflict_branches(direct, run_git) == [data["conflict"]["branch"]]
    assert run_git(direct.bare, "branch", "--list", "project-index/*").strip() == ""


def test_normal_when_conflict_script_failed(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    push_from_other_clone: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """衝突してスクリプトが失敗してもブランチは残る（正常系）。"""
    # 準備
    direct = make_direct_commit_source(
        files=NOTES, write_api_kinds=["note"], on_conflict=[sys.executable, "-c", FAILING]
    )
    env = make_server(direct.spec)
    body = _conflicting_body(direct, push_from_other_clone, run_git)
    # 実行
    response = env.client.post(URL, json=body)
    # 検証
    data = response.json()
    assert response.status_code == 200, data
    assert data["conflict"]["script"]["exitCode"] == 1
    assert data["conflict"]["script"]["stderr"] == "失敗しました\n"
    assert _conflict_branches(direct, run_git) == [data["conflict"]["branch"]]
    assert run_git(direct.folder, "rev-parse", data["conflict"]["branch"]).strip() == (
        data["conflict"]["commit"]
    )


def test_normal_when_item_versions(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    push_from_other_clone: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """項目ごとのバージョンで照合すると、別の項目の変更とは衝突しない（正常系）。"""
    # 準備
    direct = make_direct_commit_source(files=NOTES, write_api_kinds=["note"])
    env = make_server(direct.spec)
    document = env.client.get("/sources/sample/docs/notes/n1.yaml").json()
    name_version = document["itemVersions"]["name"]
    push_from_other_clone(
        direct.bare, {"notes/n1.yaml": "id: n1\nname: メモ 1\ndescription: ほかの説明\n"}
    )
    body = {
        "writes": [
            {
                "op": "update",
                "id": "n1",
                "expected_version": {"name": name_version},
                "set": {"name": "新しい名前"},
            }
        ],
        "message": "docs: n1 の名前を変える",
    }
    # 実行
    response = env.client.post(URL, json=body)
    # 検証
    data = response.json()
    assert response.status_code == 200, data
    assert data["applied"] is True
    assert data["conflict"] is None
    assert run_git(direct.bare, "show", "develop:notes/n1.yaml") == (
        "id: n1\nname: 新しい名前\ndescription: ほかの説明\n"
    )


def test_error_when_base_commit_unusable(
    tmp_path: Path,
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """編集を始めたときのコミットが起点に使えなければ断る（異常系）。"""
    # 準備
    dump = tmp_path / "env.txt"
    direct = make_direct_commit_source(
        files=NOTES,
        write_api_kinds=["note"],
        on_conflict=[sys.executable, "-c", ENV_DUMP, str(dump)],
    )
    env = make_server(direct.spec)
    (direct.folder / "memo.txt").write_text("master だけ\n", encoding="utf-8")
    run_git(direct.folder, "commit", "-am", "master だけの変更")
    master_only = run_git(direct.folder, "rev-parse", "HEAD").strip()
    before = _git_state(direct, run_git)
    worktrees_before = _worktrees(direct, run_git)
    missing = "0123456789abcdef0123456789abcdef01234567"
    # 実行
    not_found = env.client.post(URL, json=_body(direct, baseCommit=missing))
    not_ancestor = env.client.post(URL, json=_body(direct, baseCommit=master_only))
    # 検証
    assert not_found.status_code == 409, not_found.json()
    assert not_found.json()["reason"] == "not_found"
    assert not_ancestor.status_code == 409, not_ancestor.json()
    assert not_ancestor.json()["reason"] == "not_ancestor"
    assert _conflict_branches(direct, run_git) == []
    assert _worktrees(direct, run_git) == worktrees_before
    assert not dump.exists()
    assert _git_state(direct, run_git) == before


def test_error_when_invalid_at_base_commit(
    tmp_path: Path,
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    push_from_other_clone: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """編集を始めたときのコミットでも検査に合格しなければ今のブランチの理由で断る（異常系）。"""
    # 準備
    dump = tmp_path / "env.txt"
    direct = make_direct_commit_source(
        files=NOTES,
        write_api_kinds=["note"],
        on_conflict=[sys.executable, "-c", ENV_DUMP, str(dump)],
    )
    env = make_server(direct.spec)
    base = run_git(direct.develop, "rev-parse", "HEAD").strip()
    body = {
        "writes": [
            {
                "op": "update",
                "id": "n1",
                "expected_version": _version(direct.develop / "notes" / "n1.yaml"),
                "set": {"name": 1},
            }
        ],
        "message": "docs: n1 を更新する",
        "baseCommit": base,
    }
    push_from_other_clone(direct.bare, {"notes/n1.yaml": N1_CHANGED})
    worktrees_before = len(_worktrees(direct, run_git).splitlines())
    # 実行
    response = env.client.post(URL, json=body)
    # 検証
    data = response.json()
    assert response.status_code == 409, data
    assert data["title"] == "VersionMismatchError"
    assert _conflict_branches(direct, run_git) == []
    assert len(_worktrees(direct, run_git).splitlines()) == worktrees_before
    assert not dump.exists()

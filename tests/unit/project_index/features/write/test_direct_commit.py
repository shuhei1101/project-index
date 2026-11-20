from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from project_index.features.sources.types import DirectCommitConfig
from project_index.features.write.direct_commit import (
    CommitPlan,
    DirtyFiles,
    changed_paths,
    check_clean,
    commit_written,
    push_commit,
    resolve_commit_plan,
    rollback,
    run_direct_commit,
    snapshot_dirty,
    sync_worktree,
)
from project_index.features.write.types import CommitSpec
from project_index.shared.deadline import CallLimits, Deadline
from project_index.shared.errors import (
    BranchNotAllowedError,
    CommitWorktreeNotFoundError,
    DirectCommitGeneratorError,
    DirectCommitNotConfiguredError,
    FetchFailedError,
    PushFailedError,
    PushRejectedError,
    UncommittedChangesError,
    UnpushedCommitsError,
    Violation,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.sources.types import ServedSource, SourceConfig

# 書き込みの期限（NFR-11）と文書の MCP の応答の上限（NFR-10）
WRITE_DEADLINE_SEC = 32
RESPOND_BY_SEC = 48


@dataclass(frozen=True)
class Remote:
    """テスト用のベアリポジトリと、develop・data のワークツリーを持つクローン。"""

    bare: Path
    clone: Path
    develop: Path
    data: Path


@pytest.fixture(autouse=True)
def git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """コミットの作成者と、端末の git の設定を読まないことを決める。"""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "tester")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "tester@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "tester")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "tester@example.com")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")


@pytest.fixture
def remote(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
) -> Remote:
    """ベアリポジトリ・クローン本体（master）・develop と data のワークツリーを作る。"""
    bare = tmp_path / "remote.git"
    run_git(tmp_path, "init", "--bare", "-b", "master", str(bare))
    clone = git_repo(
        {"docs/a.yaml": "id: a\n", "memo.txt": "memo\n"}, name="clone", branch="master"
    )
    run_git(clone, "remote", "add", "origin", str(bare))
    run_git(clone, "branch", "develop")
    run_git(clone, "branch", "data")
    run_git(clone, "push", "origin", "master", "develop", "data")
    develop = clone / ".claude" / "worktrees" / "develop"
    data = clone / ".claude" / "worktrees" / "data"
    run_git(clone, "worktree", "add", str(develop), "develop")
    run_git(clone, "worktree", "add", str(data), "data")
    run_git(develop, "branch", "--set-upstream-to=origin/develop")
    run_git(data, "branch", "--set-upstream-to=origin/data")
    return Remote(bare=bare, clone=clone, develop=develop, data=data)


@pytest.fixture
def plan(remote: Remote) -> CommitPlan:
    """develop へ直コミットする計画を返す。"""
    return CommitPlan(
        source_id="sample",
        branch="develop",
        worktree=remote.develop,
        repo=remote.clone / ".git",
        message="docs: note を追加する",
        base=remote.develop,
    )


@pytest.fixture
def limits() -> CallLimits:
    """書き込みの期限と応答の上限を今から数える期限を返す。"""
    started = time.monotonic()
    return CallLimits(
        write_deadline=Deadline(limit_sec=WRITE_DEADLINE_SEC, started=started),
        respond_by=Deadline(limit_sec=RESPOND_BY_SEC, started=started),
    )


@pytest.fixture
def direct_source(
    remote: Remote,
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> Callable[..., ServedSource]:
    """クローンを配信元にした直コミットの配信元を作る関数を返す。"""

    def _make(**overrides: object) -> ServedSource:
        config = make_source_config(
            direct_commit=DirectCommitConfig(branch="develop", branches=["data"], kinds=["rules"])
        )
        values: dict[str, object] = {
            "root": remote.clone,
            "config": config,
            "is_git": True,
            "repo_root": remote.clone,
            "worktree_globs": [str(remote.clone / ".claude" / "worktrees" / "*")],
            "storage": "git",
        }
        values.update(overrides)
        return make_served_source(**values)

    return _make


def _push_from_other_clone(
    tmp_path: Path, remote: Remote, run_git: Callable[..., str], files: dict[str, str]
) -> None:
    """別のクローンから develop へ 1 コミットをプッシュする。"""
    other = tmp_path / "other"
    run_git(tmp_path, "clone", "-b", "develop", str(remote.bare), str(other))
    for name, content in files.items():
        (other / name).write_text(content, encoding="utf-8")
    run_git(other, "add", "-A")
    run_git(other, "commit", "-m", "other")
    run_git(other, "push", "origin", "develop")


def _install_hook(remote: Remote, name: str, script: str) -> None:
    """ベアリポジトリにフックを置く。"""
    hook = remote.bare / "hooks" / name
    hook.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
    hook.chmod(0o755)


def test_resolve_commit_plan(remote: Remote, direct_source: Callable[..., ServedSource]) -> None:
    """既定のブランチと上書きしたブランチ（正常系）。"""
    # 準備
    source = direct_source()
    # 実行
    default = resolve_commit_plan(source, CommitSpec(message="m"))
    overridden = resolve_commit_plan(source, CommitSpec(message="m", branch="data"))
    # 検証
    assert default.branch == "develop"
    assert default.worktree.resolve() == remote.develop.resolve()
    assert default.repo.resolve() == (remote.clone / ".git").resolve()
    assert overridden.branch == "data"
    assert overridden.worktree.resolve() == remote.data.resolve()
    assert overridden.repo.resolve() == (remote.clone / ".git").resolve()


def _without_config(make_config: Callable[..., SourceConfig]) -> dict[str, object]:
    """直コミットの設定を持たない配信元の値。"""
    return {"config": make_config(direct_commit=None)}


def _disk_storage(_make_config: Callable[..., SourceConfig]) -> dict[str, object]:
    """disk の配信元の値。"""
    return {"storage": "disk"}


def _with_problems(_make_config: Callable[..., SourceConfig]) -> dict[str, object]:
    """許可する種類の欠けを持つ配信元の値。"""
    return {
        "direct_commit_problems": [Violation(path="direct_commit.kinds[1]", rule="meme は無い")]
    }


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(_without_config, id="absent"),
        pytest.param(_disk_storage, id="disk"),
        pytest.param(_with_problems, id="problems"),
    ],
)
def test_resolve_commit_plan_when_not_configured(
    overrides: Callable[[Callable[..., SourceConfig]], dict[str, object]],
    direct_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> None:
    """設定が無い・disk・種類の欠け（異常系）。"""
    # 準備
    source = direct_source(**overrides(make_source_config))
    # 実行・検証
    with pytest.raises(DirectCommitNotConfiguredError, match="直コミット"):
        resolve_commit_plan(source, CommitSpec(message="m"))


def test_resolve_commit_plan_when_branch_not_allowed(
    direct_source: Callable[..., ServedSource],
) -> None:
    """上書きできないブランチ（異常系）。"""
    # 準備
    source = direct_source()
    # 実行・検証
    with pytest.raises(BranchNotAllowedError, match="master"):
        resolve_commit_plan(source, CommitSpec(message="m", branch="master"))


def test_resolve_commit_plan_when_worktree_missing(
    direct_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> None:
    """ワークツリーの無いブランチ（異常系）。"""
    # 準備
    source = direct_source(
        config=make_source_config(
            direct_commit=DirectCommitConfig(branch="main", branches=[], kinds=["rules"])
        )
    )
    # 実行・検証
    with pytest.raises(CommitWorktreeNotFoundError, match="main"):
        resolve_commit_plan(source, CommitSpec(message="m"))


def test_sync_worktree(
    tmp_path: Path, remote: Remote, plan: CommitPlan, run_git: Callable[..., str]
) -> None:
    """先に進んだリモートを取り込む（正常系）。"""
    # 準備
    _push_from_other_clone(tmp_path, remote, run_git, {"other.txt": "other\n"})
    remote_head = run_git(remote.bare, "rev-parse", "develop").strip()
    # 実行
    result = sync_worktree(plan, timeout=10)
    # 検証
    assert result == remote_head
    assert run_git(remote.develop, "rev-parse", "HEAD").strip() == remote_head


def test_sync_worktree_when_unpushed(
    remote: Remote, plan: CommitPlan, commit_all: Callable[..., str], run_git: Callable[..., str]
) -> None:
    """未プッシュのコミット（異常系）。"""
    # 準備
    local = commit_all(remote.develop, {"local.txt": "local\n"})
    # 実行・検証
    with pytest.raises(UnpushedCommitsError, match="先行 1"):
        sync_worktree(plan, timeout=10)
    assert run_git(remote.develop, "rev-parse", "HEAD").strip() == local


def test_sync_worktree_when_fetch_failed(
    tmp_path: Path, remote: Remote, plan: CommitPlan, run_git: Callable[..., str]
) -> None:
    """リモートに接続できない（異常系）。"""
    # 準備
    run_git(remote.clone, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    # 実行・検証
    with pytest.raises(FetchFailedError, match="取得できません"):
        sync_worktree(plan, timeout=10)


def test_sync_worktree_when_overwritten(
    tmp_path: Path, remote: Remote, plan: CommitPlan, run_git: Callable[..., str]
) -> None:
    """未コミットの変更が取り込む変更と重なる（異常系）。"""
    # 準備
    _push_from_other_clone(tmp_path, remote, run_git, {"memo.txt": "remote\n"})
    (remote.develop / "memo.txt").write_text("local\n", encoding="utf-8")
    # 実行・検証
    with pytest.raises(UncommittedChangesError, match=r"memo\.txt"):
        sync_worktree(plan, timeout=10)


def test_snapshot_dirty(remote: Remote, plan: CommitPlan) -> None:
    """書き換えたファイルと追跡していないファイル（正常系）。"""
    # 準備
    (remote.develop / "memo.txt").write_text("changed\n", encoding="utf-8")
    (remote.develop / "new.txt").write_text("new\n", encoding="utf-8")
    # 実行
    result = snapshot_dirty(plan)
    # 検証
    assert sorted(result.hashes) == ["memo.txt", "new.txt"]
    assert None not in result.hashes.values()


def test_check_clean_when_dirty() -> None:
    """書き込むファイルが控えにある（異常系）。"""
    # 準備
    dirty = DirtyFiles(hashes={"docs/n1.yaml": "abc"})
    # 実行・検証
    with pytest.raises(UncommittedChangesError, match=r"docs/n1\.yaml"):
        check_clean(dirty, ["docs/n1.yaml", "docs/n2.yaml"])


def test_changed_paths(remote: Remote, plan: CommitPlan) -> None:
    """配信元のフォルダの配下の差だけ（正常系）。"""
    # 準備
    before = snapshot_dirty(plan)
    note = remote.develop / "docs" / "n1.yaml"
    note.write_text("id: n1\n", encoding="utf-8")
    (remote.develop / "docs" / "index.md").write_text("# 一覧\n", encoding="utf-8")
    outside = remote.develop / ".claude" / "tmp.txt"
    outside.parent.mkdir(parents=True)
    outside.write_text("tmp\n", encoding="utf-8")
    scoped = CommitPlan(
        source_id=plan.source_id,
        branch=plan.branch,
        worktree=plan.worktree,
        repo=plan.repo,
        message=plan.message,
        base=remote.develop / "docs",
    )
    # 実行
    written, unknown = changed_paths(scoped, before, [note])
    # 検証
    assert sorted(written) == ["docs/index.md", "docs/n1.yaml"]
    assert unknown == []


def test_changed_paths_when_dirty_changed(remote: Remote, plan: CommitPlan) -> None:
    """見分けられないパス（正常系）。"""
    # 準備
    index = remote.develop / "docs" / "index.md"
    index.write_text("# 前\n", encoding="utf-8")
    before = snapshot_dirty(plan)
    index.write_text("# 後\n", encoding="utf-8")
    # 実行
    written, unknown = changed_paths(plan, before, [])
    # 検証
    assert written == []
    assert unknown == ["docs/index.md"]


def test_commit_written(remote: Remote, plan: CommitPlan, run_git: Callable[..., str]) -> None:
    """書き込んだファイルと生成物だけ（正常系）。"""
    # 準備
    (remote.develop / "memo.txt").write_text("changed\n", encoding="utf-8")
    before = snapshot_dirty(plan)
    note = remote.develop / "docs" / "n1.yaml"
    note.write_text("id: n1\n", encoding="utf-8")
    (remote.develop / "docs" / "index.md").write_text("# 一覧\n", encoding="utf-8")
    # 実行
    sha, paths = commit_written(plan, before, [note])
    # 検証
    committed = run_git(remote.develop, "show", "--name-only", "--format=", sha).split()
    assert sorted(committed) == ["docs/index.md", "docs/n1.yaml"]
    assert sorted(paths) == ["docs/index.md", "docs/n1.yaml"]
    assert run_git(remote.develop, "status", "--porcelain").strip() == "M memo.txt"


def test_commit_written_when_staged_other(
    remote: Remote, plan: CommitPlan, run_git: Callable[..., str]
) -> None:
    """他にステージされた変更（正常系）。"""
    # 準備
    (remote.develop / "memo.txt").write_text("changed\n", encoding="utf-8")
    run_git(remote.develop, "add", "memo.txt")
    before = snapshot_dirty(plan)
    note = remote.develop / "docs" / "n1.yaml"
    note.write_text("id: n1\n", encoding="utf-8")
    # 実行
    sha, _ = commit_written(plan, before, [note])
    # 検証
    committed = run_git(remote.develop, "show", "--name-only", "--format=", sha).split()
    assert committed == ["docs/n1.yaml"]
    assert run_git(remote.develop, "diff", "--cached", "--name-only").split() == ["memo.txt"]


def test_commit_written_when_generator_touched_dirty(
    remote: Remote, plan: CommitPlan, run_git: Callable[..., str]
) -> None:
    """生成が未コミットの変更のあるファイルを書き換えた（異常系）。"""
    # 準備
    index = remote.develop / "docs" / "index.md"
    index.write_text("# 前\n", encoding="utf-8")
    before = snapshot_dirty(plan)
    head = run_git(remote.develop, "rev-parse", "HEAD").strip()
    note = remote.develop / "docs" / "n1.yaml"
    note.write_text("id: n1\n", encoding="utf-8")
    index.write_text("# 後\n", encoding="utf-8")
    # 実行・検証
    with pytest.raises(UncommittedChangesError, match=r"docs/index\.md"):
        commit_written(plan, before, [note])
    assert run_git(remote.develop, "rev-parse", "HEAD").strip() == head


def test_push_commit(
    remote: Remote, plan: CommitPlan, commit_all: Callable[..., str], run_git: Callable[..., str]
) -> None:
    """届く（正常系）。"""
    # 準備
    sha = commit_all(remote.develop, {"docs/n1.yaml": "id: n1\n"})
    # 実行
    result = push_commit(plan, sha, timeout=10)
    # 検証
    assert result.state == "pushed"
    assert run_git(remote.bare, "rev-parse", "develop").strip() == sha


def test_push_commit_when_rejected(
    remote: Remote, plan: CommitPlan, commit_all: Callable[..., str]
) -> None:
    """断られる（正常系）。"""
    # 準備
    _install_hook(remote, "pre-receive", "echo 'denied by policy' >&2\nexit 1")
    sha = commit_all(remote.develop, {"docs/n1.yaml": "id: n1\n"})
    # 実行
    result = push_commit(plan, sha, timeout=10)
    # 検証
    assert result.state == "rejected"
    assert result.reason != ""


def test_push_commit_when_delivered_but_failed(
    remote: Remote, plan: CommitPlan, commit_all: Callable[..., str], run_git: Callable[..., str]
) -> None:
    """届いた後に失敗が返る（正常系）。"""
    # 準備
    _install_hook(remote, "post-receive", "sleep 5")
    sha = commit_all(remote.develop, {"docs/n1.yaml": "id: n1\n"})
    # 実行
    result = push_commit(plan, sha, timeout=1)
    # 検証
    assert result.state == "pushed"
    assert run_git(remote.bare, "rev-parse", "develop").strip() == sha


def test_push_commit_when_unreachable(
    tmp_path: Path,
    remote: Remote,
    plan: CommitPlan,
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """届かない（正常系）。"""
    # 準備
    run_git(remote.clone, "remote", "set-url", "--push", "origin", str(tmp_path / "missing.git"))
    sha = commit_all(remote.develop, {"docs/n1.yaml": "id: n1\n"})
    # 実行
    result = push_commit(plan, sha, timeout=10)
    # 検証
    assert result.state == "failed"


def test_push_commit_when_no_time(
    remote: Remote, plan: CommitPlan, commit_all: Callable[..., str], run_git: Callable[..., str]
) -> None:
    """時間が残っていない（正常系）。"""
    # 準備
    remote_head = run_git(remote.bare, "rev-parse", "develop").strip()
    sha = commit_all(remote.develop, {"docs/n1.yaml": "id: n1\n"})
    # 実行
    result = push_commit(plan, sha, timeout=0)
    # 検証
    assert result.state == "failed"
    assert run_git(remote.bare, "rev-parse", "develop").strip() == remote_head


def test_rollback(remote: Remote, plan: CommitPlan, run_git: Callable[..., str]) -> None:
    """コミットとファイルを戻す（正常系）。"""
    # 準備
    base = run_git(remote.develop, "rev-parse", "HEAD").strip()
    (remote.develop / "memo.txt").write_text("staged\n", encoding="utf-8")
    run_git(remote.develop, "add", "memo.txt")
    (remote.develop / "docs" / "n1.yaml").write_text("id: n1\n", encoding="utf-8")
    (remote.develop / "docs" / "a.yaml").write_text("id: a2\n", encoding="utf-8")
    run_git(remote.develop, "add", "docs/n1.yaml", "docs/a.yaml")
    run_git(remote.develop, "commit", "-m", "x", "--", "docs/n1.yaml", "docs/a.yaml")
    # 実行
    rollback(plan, base, ["docs/n1.yaml", "docs/a.yaml"])
    # 検証
    assert run_git(remote.develop, "rev-parse", "HEAD").strip() == base
    assert not (remote.develop / "docs" / "n1.yaml").exists()
    assert (remote.develop / "docs" / "a.yaml").read_text(encoding="utf-8") == "id: a\n"
    assert run_git(remote.develop, "diff", "--cached", "--name-only").split() == ["memo.txt"]


def test_run_direct_commit(
    remote: Remote, plan: CommitPlan, limits: CallLimits, run_git: Callable[..., str]
) -> None:
    """1 回で届く（正常系）。"""
    # 準備
    remote_before = run_git(remote.bare, "rev-parse", "develop").strip()

    def write_once(_dirty: DirtyFiles) -> list[Path]:
        note = remote.develop / "docs" / "n1.yaml"
        note.write_text("id: n1\n", encoding="utf-8")
        return [note]

    # 実行
    result = run_direct_commit(plan, write_once, limits=limits)
    # 検証
    assert result.retried is False
    assert result.branch == "develop"
    assert run_git(remote.bare, "rev-parse", "develop").strip() == result.sha
    assert run_git(remote.bare, "rev-parse", f"{result.sha}~1").strip() == remote_before


def test_run_direct_commit_when_rejected_once(
    remote: Remote, plan: CommitPlan, limits: CallLimits, run_git: Callable[..., str]
) -> None:
    """1 回断られる（正常系）。"""
    # 準備
    marker = remote.bare / "rejected-once"
    _install_hook(
        remote, "pre-receive", f'if [ ! -f "{marker}" ]; then touch "{marker}"; exit 1; fi\nexit 0'
    )
    remote_before = run_git(remote.bare, "rev-parse", "develop").strip()
    calls: list[int] = []

    def write_once(_dirty: DirtyFiles) -> list[Path]:
        calls.append(1)
        note = remote.develop / "docs" / "n1.yaml"
        note.write_text("id: n1\n", encoding="utf-8")
        return [note]

    # 実行
    result = run_direct_commit(plan, write_once, limits=limits)
    # 検証
    assert len(calls) == 2
    assert result.retried is True
    assert run_git(remote.bare, "rev-parse", "develop").strip() == result.sha
    assert run_git(remote.bare, "rev-parse", f"{result.sha}~1").strip() == remote_before


def test_run_direct_commit_when_rejected_twice(
    remote: Remote, plan: CommitPlan, limits: CallLimits, run_git: Callable[..., str]
) -> None:
    """2 回断られる（異常系）。"""
    # 準備
    _install_hook(remote, "pre-receive", "exit 1")
    base = run_git(remote.develop, "rev-parse", "HEAD").strip()

    def write_once(_dirty: DirtyFiles) -> list[Path]:
        note = remote.develop / "docs" / "n1.yaml"
        note.write_text("id: n1\n", encoding="utf-8")
        return [note]

    # 実行・検証
    with pytest.raises(PushRejectedError, match="断られました"):
        run_direct_commit(plan, write_once, limits=limits)
    assert run_git(remote.develop, "rev-parse", "HEAD").strip() == base
    assert run_git(remote.develop, "status", "--porcelain").strip() == ""


def test_run_direct_commit_when_write_failed(
    remote: Remote, plan: CommitPlan, limits: CallLimits, run_git: Callable[..., str]
) -> None:
    """書き込みが例外（異常系）。"""
    # 準備
    base = run_git(remote.develop, "rev-parse", "HEAD").strip()

    def write_once(_dirty: DirtyFiles) -> list[Path]:
        (remote.develop / "docs" / "n1.yaml").write_text("id: n1\n", encoding="utf-8")
        (remote.develop / "docs" / "a.yaml").write_text("id: a2\n", encoding="utf-8")
        raise DirectCommitGeneratorError(message="生成が失敗しました")

    # 実行・検証
    with pytest.raises(DirectCommitGeneratorError, match="生成が失敗しました"):
        run_direct_commit(plan, write_once, limits=limits)
    assert run_git(remote.develop, "rev-parse", "HEAD").strip() == base
    assert run_git(remote.develop, "status", "--porcelain").strip() == ""


def test_run_direct_commit_when_push_failed(
    tmp_path: Path,
    remote: Remote,
    plan: CommitPlan,
    limits: CallLimits,
    run_git: Callable[..., str],
) -> None:
    """届かない（異常系）。"""
    # 準備
    run_git(remote.clone, "remote", "set-url", "--push", "origin", str(tmp_path / "missing.git"))
    base = run_git(remote.develop, "rev-parse", "HEAD").strip()

    def write_once(_dirty: DirtyFiles) -> list[Path]:
        note = remote.develop / "docs" / "n1.yaml"
        note.write_text("id: n1\n", encoding="utf-8")
        return [note]

    # 実行・検証
    with pytest.raises(PushFailedError, match="プッシュできませんでした"):
        run_direct_commit(plan, write_once, limits=limits)
    assert run_git(remote.develop, "rev-parse", "HEAD").strip() == base

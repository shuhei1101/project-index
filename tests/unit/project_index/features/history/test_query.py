from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from project_index.features.history.query import (
    changed_files,
    co_changed_files,
    file_dates,
    list_commits,
    list_refs,
    read_file_at,
    resolve_ref,
)
from project_index.features.history.types import CommitStep, FileChange, FileDates
from project_index.shared.errors import RefNotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.sources.types import ServedSource, SourceConfig

OCT_01 = "2026-10-01T12:00:00+09:00"
OCT_03 = "2026-10-03T12:00:00+09:00"
OCT_05 = "2026-10-05T12:00:00+09:00"
OCT_07 = "2026-10-07T12:00:00+09:00"


def test_resolve_ref(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
) -> None:
    """ブランチを解く（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"}, branch="main")
    second = commit_all(root, {"a.yaml": "a: 2\n"})
    # 実行
    result = resolve_ref(root, "main", date_base="main")
    # 検証
    assert result.commit == second
    assert result.input == "main"


def test_resolve_ref_when_date(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """日時をその時点の最後の commit に解く（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"}, branch="main", date=OCT_01)
    first = run_git(root, "rev-parse", "HEAD").strip()
    commit_all(root, {"a.yaml": "a: 2\n"}, date=OCT_05)
    # 実行
    result = resolve_ref(root, "2026-10-03", date_base="main")
    # 検証
    assert result.commit == first


def test_resolve_ref_when_not_found(git_repo: Callable[..., Path]) -> None:
    """無いリビジョン（異常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"}, branch="main")
    # 実行・検証
    with pytest.raises(RefNotFoundError) as exc_info:
        resolve_ref(root, "nope", date_base="main", argument="from")
    assert exc_info.value.argument == "from"
    assert exc_info.value.value == "nope"


def test_resolve_ref_when_before_first(git_repo: Callable[..., Path]) -> None:
    """最初の commit より前の日時（異常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"}, branch="main", date=OCT_01)
    # 実行・検証
    with pytest.raises(RefNotFoundError):
        resolve_ref(root, "2000-01-01", date_base="main")


def test_list_refs(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> None:
    """ブランチ・タグ・commit を返す（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"}, branch="main")
    run_git(root, "branch", "feat/x")
    tagged = run_git(root, "rev-parse", "--short=7", "HEAD").strip()
    run_git(root, "tag", "-a", "v0.1.0", "-m", "release")
    commit_all(root, {"a.yaml": "a: 2\n"})
    commit_all(root, {"a.yaml": "a: 3\n"})
    head = run_git(root, "rev-parse", "--short=7", "HEAD").strip()
    previous = run_git(root, "rev-parse", "--short=7", "HEAD~1").strip()
    source = make_served_source(
        root=root,
        is_git=True,
        repo_root=root,
        config=make_source_config(default_ref="main"),
    )
    # 実行
    result = list_refs(source, commits=2)
    # 検証
    assert len(result.branches) == 2
    assert result.tags[0].commit == tagged
    assert [item.commit for item in result.commits] == [head, previous]


def test_list_refs_when_not_git(make_served_source: Callable[..., ServedSource]) -> None:
    """Git の管理外（正常系）。"""
    # 準備
    source = make_served_source(is_git=False)
    # 実行
    result = list_refs(source)
    # 検証
    assert result.git is False
    assert result.branches == []
    assert result.tags == []
    assert result.commits == []


def test_changed_files(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """commit の間（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n", "c.yaml": "c: 1\n"})
    first = run_git(root, "rev-parse", "HEAD").strip()
    second = commit_all(root, {"a.yaml": "a: 2\n", "b.yaml": "b: 1\n"}, delete=("c.yaml",))
    # 実行
    result = changed_files(root, first, second)
    # 検証
    assert result == [
        FileChange(path="a.yaml", change="modified"),
        FileChange(path="b.yaml", change="added"),
        FileChange(path="c.yaml", change="deleted"),
    ]


def test_changed_files_when_work_tree(
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    write_files: Callable[[Path, dict[str, str]], None],
) -> None:
    """作業ツリーとの間。未追跡も含む（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    head = run_git(root, "rev-parse", "HEAD").strip()
    write_files(root, {"a.yaml": "a: 2\n", "n.yaml": "n: 1\n"})
    # 実行
    result = changed_files(root, head)
    # 検証
    assert result == [
        FileChange(path="a.yaml", change="modified"),
        FileChange(path="n.yaml", change="added"),
    ]


def test_changed_files_when_pathspec(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """配信元のフォルダで絞る（正常系）。"""
    # 準備
    root = git_repo({"docs/a.yaml": "a: 1\n", "src/x.py": "x = 1\n"})
    first = run_git(root, "rev-parse", "HEAD").strip()
    second = commit_all(root, {"docs/a.yaml": "a: 2\n", "src/x.py": "x = 2\n"})
    # 実行
    result = changed_files(root, first, second, pathspec="docs")
    # 検証
    assert result == [FileChange(path="docs/a.yaml", change="modified")]


def test_file_dates(git_repo: Callable[..., Path], commit_all: Callable[..., str]) -> None:
    """最初と最後の commit（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"}, date=OCT_01)
    commit_all(root, {"b.yaml": "b: 1\n"}, date=OCT_03)
    commit_all(root, {"a.yaml": "a: 2\n"}, date=OCT_05)
    # 実行
    result = file_dates(root)
    # 検証
    assert result["a.yaml"] == FileDates(
        created=datetime.fromisoformat(OCT_01), updated=datetime.fromisoformat(OCT_05)
    )
    assert result["b.yaml"] == FileDates(
        created=datetime.fromisoformat(OCT_03), updated=datetime.fromisoformat(OCT_03)
    )


def test_co_changed_files(git_repo: Callable[..., Path], commit_all: Callable[..., str]) -> None:
    """一緒に変わった回数を数える（正常系）。"""
    # 準備
    root = git_repo({"a": "0\n"})
    commit_all(root, {"a": "1\n", "b": "1\n"})
    commit_all(root, {"a": "2\n", "b": "2\n"})
    commit_all(root, {"a": "3\n", "c": "1\n"})
    # 実行
    result = co_changed_files(root, ["a"])
    # 検証
    assert result == {"b": 2, "c": 1}


def test_read_file_at(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """前の内容を読む（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    first = run_git(root, "rev-parse", "HEAD").strip()
    commit_all(root, {"a.yaml": "a: 2\n"})
    # 実行
    result = read_file_at(root, first, "a.yaml")
    # 検証
    assert result == "a: 1\n"


def test_read_file_at_when_missing(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """その commit に無い（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    first = run_git(root, "rev-parse", "HEAD").strip()
    commit_all(root, {"later.yaml": "x: 1\n"})
    # 実行
    result = read_file_at(root, first, "later.yaml")
    # 検証
    assert result is None


def test_list_commits(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """区間の commit と親（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 0\n"}, date=OCT_01)
    base = run_git(root, "rev-parse", "HEAD").strip()
    first = commit_all(root, {"a.yaml": "a: 1\n"}, date=OCT_03)
    second = commit_all(root, {"a.yaml": "a: 2\n"}, date=OCT_05)
    third = commit_all(root, {"a.yaml": "a: 3\n"}, date=OCT_07)
    # 実行
    result = list_commits(root, base, "HEAD")
    # 検証
    assert result == [
        CommitStep(
            commit=first,
            date=datetime.fromisoformat(OCT_03),
            parent=base,
            parent_date=datetime.fromisoformat(OCT_01),
        ),
        CommitStep(
            commit=second,
            date=datetime.fromisoformat(OCT_05),
            parent=first,
            parent_date=datetime.fromisoformat(OCT_03),
        ),
        CommitStep(
            commit=third,
            date=datetime.fromisoformat(OCT_07),
            parent=second,
            parent_date=datetime.fromisoformat(OCT_05),
        ),
    ]


def test_list_commits_when_merge(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
) -> None:
    """マージ commit を除く（正常系）。"""
    # 準備
    root = git_repo({"a.yaml": "a: 0\n"})
    base = run_git(root, "rev-parse", "HEAD").strip()
    run_git(root, "checkout", "-b", "feature")
    branch_commit = commit_all(root, {"b.yaml": "b: 1\n"})
    run_git(root, "checkout", "develop")
    run_git(root, "merge", "--no-ff", "feature", "-m", "merge")
    # 実行
    result = list_commits(root, base, "HEAD")
    # 検証
    assert [step.commit for step in result] == [branch_commit]


def test_list_worktrees(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    make_served_source: Callable[..., ServedSource],
) -> None:
    """glob に当たるワークツリー（正常系）。"""
    from project_index.features.history.query import list_worktrees

    # 準備
    root = git_repo({"a.yaml": "a: 1\n"})
    run_git(root, "worktree", "add", "-b", "feat/x", str(root / ".claude/worktrees/x"))
    run_git(root, "worktree", "add", "--detach", str(root / ".claude/worktrees/y"))
    run_git(root, "worktree", "add", "-b", "feat/z", str(tmp_path / "z"))
    source = make_served_source(
        root=root,
        is_git=True,
        repo_root=root,
        worktree_globs=[str(root / ".claude/worktrees/*")],
    )
    # 実行
    result = list_worktrees(source)
    # 検証
    assert [(Path(item.path).resolve(), item.branch) for item in result] == [
        ((root / ".claude/worktrees/x").resolve(), "feat/x"),
        ((root / ".claude/worktrees/y").resolve(), None),
    ]


def test_export_paths_at(git_repo: Callable[..., Path], run_git: Callable[..., str]) -> None:
    """commit のフォルダを取り出す（正常系）。"""
    from project_index.features.history.query import export_paths_at

    # 準備
    root = git_repo({"scripts/a.py": 'print("develop")\n'})
    commit = run_git(root, "rev-parse", "HEAD").strip()
    (root / "scripts/a.py").write_text('print("disk")\n', encoding="utf-8")
    # 実行
    with export_paths_at(root, commit, ["scripts"]) as exported:
        content = (exported / "scripts/a.py").read_text(encoding="utf-8")
    # 検証
    assert content == 'print("develop")\n'
    assert not exported.exists()

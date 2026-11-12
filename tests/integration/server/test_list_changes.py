from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from project_index.shared.hashing import content_hash

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

DOC_1 = {"field": "id", "op": "eq", "values": ["doc-1"]}
SHORT_SHA = 7
WORD = "廃止予定"
OUTSIDE_LINE = "作業範囲の外（参考）"
OUTSIDE_LOG = "作業範囲の外を読んだ"


def _changed_source(
    make_source: Callable[..., Any],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    sample_doc_text: Callable[..., str],
    *,
    date: str | None = None,
) -> tuple[Any, str, str]:
    """文書 1 の name を変えた commit を持つ sample と、親の commit・変更の commit を返す。"""
    source = make_source("sample", date=date)
    parent = run_git(source.folder, "rev-parse", "HEAD").strip()
    renamed = sample_doc_text("doc-1", "新しい名前", description="1 件目", tags=["a"])
    changed = commit_all(
        source.folder, {"docs/doc-1.yaml": renamed}, "docs: 改名", date="2026-02-01T00:00:00+09:00"
    )
    return source, parent, changed


def _word_history(
    make_source: Callable[..., Any],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    sample_doc_text: Callable[..., str],
) -> tuple[Any, str, str, str]:
    """文書 1 に語が入り、書き換えられ、消えた 3 つの commit を持つ sample と、各 commit を返す。"""
    source = make_source("sample")
    base = run_git(source.folder, "rev-parse", "HEAD").strip()
    with_word = sample_doc_text("doc-1", "文書 1", description=f"1 件目 {WORD}", tags=["a"])
    rewritten = sample_doc_text("doc-1", "文書 1", description=f"1 件目 {WORD}です", tags=["a"])
    original = sample_doc_text("doc-1", "文書 1", description="1 件目", tags=["a"])
    added = commit_all(source.folder, {"docs/doc-1.yaml": with_word}, "docs: 語を足す")
    commit_all(
        source.folder,
        {
            "docs/doc-1.yaml": rewritten,
            "docs/doc-2.yaml": sample_doc_text(
                "doc-2", "文書 2 改", description="2 件目", tags=["a", "b"]
            ),
        },
        "docs: 書き換える",
    )
    removed = commit_all(source.folder, {"docs/doc-1.yaml": original}, "docs: 語を消す")
    return source, base, added, removed


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    sample_doc_text: Callable[..., str],
) -> None:
    """2 つの commit の間に変わった文書とキー、差分の行を返す（正常系）。"""
    # 準備
    source, parent, changed = _changed_source(
        make_source, commit_all, run_git, sample_doc_text, date="2026-01-01T00:00:00+09:00"
    )
    env = make_server(source)
    arguments = {"cwd": str(source.folder), "source": "sample", "from": parent, "to": changed}
    # 実行
    summary = env.call("list_changes", format="json", **arguments)
    markdown = env.call("list_changes", **arguments)
    full = env.call("list_changes", view="full", format="json", **arguments)
    full_markdown = env.call("list_changes", view="full", **arguments)
    # 検証
    items = summary.data["items"]
    assert parent.startswith(summary.data["range"]["from"]["commit"])
    assert changed.startswith(summary.data["range"]["to"]["commit"])
    assert [(item["id"], item["change"], item["keys"]) for item in items] == [
        ("doc-1", "modified", ["name"])
    ]
    assert parent[:SHORT_SHA] in markdown.text
    assert changed[:SHORT_SHA] in markdown.text
    assert "- name: 文書 1" in full.data["items"][0]["diff"]
    assert "+ name: 新しい名前" in full.data["items"][0]["diff"]
    assert "path" not in full.data["items"][0]
    assert "scope" not in full.data["items"][0]
    assert "+ name: 新しい名前" in full_markdown.text
    assert "<document" not in full_markdown.text


def test_normal_when_range_by_date_and_branch(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    sample_doc_text: Callable[..., str],
) -> None:
    """日時とブランチ名を commit に解決して比べる（正常系）。"""
    # 準備
    source, parent, changed = _changed_source(
        make_source, commit_all, run_git, sample_doc_text, date="2026-01-01T00:00:00+09:00"
    )
    run_git(source.folder, "branch", "feat/range", changed)
    env = make_server(source)
    # 実行
    result = env.call(
        "list_changes",
        cwd=str(source.folder),
        source="sample",
        format="json",
        **{"from": "2026-01-15", "to": "feat/range"},
    )
    # 検証
    assert parent.startswith(result.data["range"]["from"]["commit"])
    assert changed.startswith(result.data["range"]["to"]["commit"])
    assert [(item["id"], item["keys"]) for item in result.data["items"]] == [("doc-1", ["name"])]


def test_normal_when_since_last_read(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
) -> None:
    """from を省き、この会話で前回読んだ内容と今の内容を比べる（正常系）。"""
    # 準備
    sample = make_source("sample")
    notes = make_source("notes", git=False, scope_read=[sample.folder])
    worktree = add_worktree(sample.folder, "x")
    env = make_server(sample, notes)
    read = {"session_id": "s1", "view": "full"}
    env.call("search_docs", cwd=str(sample.folder), worktree=str(worktree), **read)
    env.call("search_docs", cwd=str(sample.folder), source="notes", **read)
    target = worktree / "docs" / "doc-1.yaml"
    env.call(
        "write_docs",
        cwd=str(sample.folder),
        worktree=str(worktree),
        operations=[
            {
                "op": "update",
                "id": "doc-1",
                "expected_version": content_hash(target.read_text(encoding="utf-8")),
                "set": {"name": "新しい名前"},
            }
        ],
    )
    notes_doc = notes.folder / "docs" / "doc-2.yaml"
    notes_doc.write_text("id: doc-2\nname: メモの新しい名前\n", encoding="utf-8")
    # 実行
    in_git = env.call(
        "list_changes",
        cwd=str(sample.folder),
        worktree=str(worktree),
        session_id="s1",
        format="json",
    )
    in_notes = env.call(
        "list_changes", cwd=str(sample.folder), source="notes", session_id="s1", format="json"
    )
    in_git_full = env.call(
        "list_changes",
        cwd=str(sample.folder),
        worktree=str(worktree),
        session_id="s1",
        view="full",
        format="json",
    )
    # 検証
    assert [(item["id"], item["keys"]) for item in in_git.data["items"]] == [("doc-1", ["name"])]
    assert in_git.data["items"][0]["path"] == f"{worktree}/docs/doc-1.yaml"
    assert in_git.data["items"][0]["scope"] == "summary"
    assert in_git_full.data["items"][0]["scope"] == "section"
    assert [item["id"] for item in in_notes.data["items"]] == ["doc-2"]


def test_error_when_ref_not_found(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """解決できない区間を断る（異常系）。"""
    # 準備
    source = make_source("sample")
    env = make_server(source)
    # 実行
    result = env.call(
        "list_changes", cwd=str(source.folder), source="sample", **{"from": "no-such-branch"}
    )
    # 検証
    assert result.is_error
    assert "RefNotFoundError" in result.text
    assert "no-such-branch" in result.text
    assert "from" in result.text


def test_error_when_last_read_not_found(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """読んだ記録の無い会話で from を省くと断る（異常系）。"""
    # 準備
    source = make_source("sample")
    env = make_server(source)
    # 実行
    result = env.call("list_changes", cwd=str(source.folder), session_id="s2")
    # 検証
    assert result.is_error
    assert "LastReadNotFoundError" in result.text
    assert "from" in result.text


def test_error_when_invalid_argument(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """Git 管理外の配信元への区間の指定と、from の無い to を断る（異常系）。"""
    # 準備
    sample = make_source("sample")
    notes = make_source("notes", git=False, scope_read=[sample.folder])
    env = make_server(sample, notes)
    # 実行
    non_git = env.call("list_changes", cwd=str(sample.folder), source="notes", **{"from": "HEAD~1"})
    only_to = env.call("list_changes", cwd=str(sample.folder), source="sample", to="develop")
    empty_word = env.call(
        "list_changes", cwd=str(sample.folder), source="sample", contains={"value": ""}
    )
    bad_regex = env.call(
        "list_changes",
        cwd=str(sample.folder),
        source="sample",
        contains={"value": "(", "regex": True},
    )
    # 検証
    assert non_git.is_error
    assert "InvalidArgumentError" in non_git.text
    assert "notes" in non_git.text
    assert only_to.is_error
    assert "InvalidArgumentError" in only_to.text
    assert "from" in only_to.text
    assert empty_word.is_error
    assert "contains.value" in empty_word.text
    assert bad_regex.is_error
    assert "InvalidArgumentError" in bad_regex.text
    assert "contains.value" in bad_regex.text


def test_error_when_source_not_readable(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    sample_doc_text: Callable[..., str],
) -> None:
    """scope に当たらない配信元の変更を返さない（異常系）。"""
    # 準備
    sample, parent, changed = _changed_source(make_source, commit_all, run_git, sample_doc_text)
    other = make_source("other")
    env = make_server(sample, other)
    # 実行
    single = env.call(
        "list_changes", cwd=str(sample.folder), source="other", **{"from": parent, "to": changed}
    )
    everything = env.call(
        "list_changes",
        cwd=str(sample.folder),
        source="*",
        format="json",
        **{"from": parent, "to": changed},
    )
    # 検証
    assert single.is_error
    assert "SourceNotReadableError" in single.text
    assert "other" in single.text
    assert "sample" in single.text
    assert not everything.is_error
    assert "other" not in everything.text


def test_normal_when_contains(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    commit_all: Callable[..., str],
    run_git: Callable[..., str],
    sample_doc_text: Callable[..., str],
) -> None:
    """contains で、区間の中で語の出現数が変わった文書と、入った・消えた区間を返す（正常系）。"""
    # 準備
    source, base, added, removed = _word_history(make_source, commit_all, run_git, sample_doc_text)
    env = make_server(source)
    cwd = str(source.folder)
    range_arguments = {"cwd": cwd, "source": "sample", "from": base, "to": removed}
    word = {"value": WORD}
    # 実行
    result = env.call("list_changes", format="json", contains=word, **range_arguments)
    markdown = env.call("list_changes", contains=word, **range_arguments)
    regex = env.call(
        "list_changes",
        format="json",
        contains={"value": "廃止.定", "regex": True},
        **range_arguments,
    )
    without_contains = env.call("list_changes", format="json", **range_arguments)
    # 前回読んだ時点から比べる呼び出しの準備（文書 1 を読んでから、語を足す）
    env.call("search_docs", cwd=cwd, filter=DOC_1, view="full", session_id="s1")
    doc_1_path = source.folder / "docs" / "doc-1.yaml"
    doc_1_path.write_text(
        sample_doc_text("doc-1", "文書 1", description=f"1 件目 {WORD}", tags=["a"]),
        encoding="utf-8",
    )
    since_last_read = env.call(
        "list_changes", cwd=cwd, source="sample", session_id="s1", format="json", contains=word
    )
    # ブランチで文書 2 に語を足し、--no-ff でマージする。文書 1 の語は作業ツリーに残す
    run_git(source.folder, "stash")
    run_git(source.folder, "checkout", "-b", "feature")
    doc_2 = sample_doc_text("doc-2", "文書 2 改", description=f"2 件目 {WORD}", tags=["a", "b"])
    branch = commit_all(source.folder, {"docs/doc-2.yaml": doc_2}, "docs: ブランチで語を足す")
    run_git(source.folder, "checkout", "develop")
    run_git(source.folder, "merge", "--no-ff", "feature", "-m", "merge")
    run_git(source.folder, "stash", "pop")
    to_worktree = env.call(
        "list_changes",
        cwd=cwd,
        source="sample",
        format="json",
        contains=word,
        **{"from": base},
    )
    # 検証
    item = result.data["items"][0]
    assert [(entry["id"], entry["change"]) for entry in result.data["items"]] == [
        ("doc-1", "unchanged")
    ]
    assert [
        (change["kind"], change["to"]["commit"], change["count_before"], change["count_after"])
        for change in item["contains_changes"]
    ] == [("added", added[:SHORT_SHA], 0, 1), ("removed", removed[:SHORT_SHA], 1, 0)]
    assert regex.data["items"] == result.data["items"]
    assert [entry["id"] for entry in without_contains.data["items"]] == ["doc-2"]
    assert "contains_changes" not in without_contains.data["items"][0]
    assert f"added {added[:SHORT_SHA]}・removed {removed[:SHORT_SHA]}" in markdown.text
    last_read_changes = since_last_read.data["items"][0]["contains_changes"]
    assert [change["kind"] for change in last_read_changes] == ["added"]
    assert last_read_changes[0]["from"] == since_last_read.data["range"]["from"]
    assert last_read_changes[0]["to"] == since_last_read.data["range"]["to"]
    by_id = {entry["id"]: entry["contains_changes"] for entry in to_worktree.data["items"]}
    assert [(change["kind"], change["to"]["commit"]) for change in by_id["doc-2"]] == [
        ("added", branch[:SHORT_SHA])
    ]
    assert by_id["doc-1"][-1]["kind"] == "added"
    assert by_id["doc-1"][-1]["to"] == {"input": "作業ツリー"}


def test_normal_when_outside_scope(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    commit_all: Callable[..., str],
    sample_doc_text: Callable[..., str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """outside_scope: true で、scope に当たらない配信元の変更を作業範囲の外として返す（正常系）。"""
    # 準備
    sample = make_source("sample")
    other = make_source("other")
    closed = make_source("closed", outside_read=False)
    renamed = sample_doc_text("doc-1", "新しい名前", description="1 件目", tags=["a"])
    commit_all(other.folder, {"docs/doc-1.yaml": renamed}, "docs: 改名")
    commit_all(closed.folder, {"docs/doc-1.yaml": renamed}, "docs: 改名")
    env = make_server(sample, other, closed)
    cwd = str(sample.folder)
    caplog.set_level(logging.INFO)
    # 実行
    result = env.call(
        "list_changes", cwd=cwd, source="other", outside_scope=True, **{"from": "HEAD~1"}
    )
    as_json = env.call(
        "list_changes",
        cwd=cwd,
        source="other",
        outside_scope=True,
        format="json",
        **{"from": "HEAD~1"},
    )
    refused = env.call(
        "list_changes", cwd=cwd, source="closed", outside_scope=True, **{"from": "HEAD~1"}
    )
    # 検証
    logs = [record.getMessage() for record in caplog.records if OUTSIDE_LOG in record.getMessage()]
    assert not result.is_error
    assert result.text.splitlines()[0] == OUTSIDE_LINE
    assert [(item["id"], item["change"]) for item in as_json.data["items"]] == [
        ("doc-1", "modified")
    ]
    assert any(cwd in message and "other" in message for message in logs)
    assert refused.is_error
    assert "SourceNotReadableError" in refused.text

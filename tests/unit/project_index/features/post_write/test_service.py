from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.post_write.notified import NotifiedStore
from project_index.features.post_write.service import classify_path, judge_post_write
from project_index.features.post_write.types import NOTICE_PROMPT_ID, PostWriteRequest
from project_index.features.prompt_doc.runtime import DEFAULT_PROMPTS_DIR, load_prompts
from project_index.features.sources.types import DocumentTable

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.prompt_doc.runtime import PromptSet
    from project_index.features.sources.types import ServedSource, SourceConfig

# 範囲の Markdown の管理用の YAML の行（docs/files.yml が docs/ の配下を受け持つ）
FILES_TABLE = DocumentTable(
    id="files",
    paths=["docs/files.yml"],
    schema_path="schemas/files.schema.yaml",
    records="files",
    body_file="path",
)
# YAML の文書の行
RULES_TABLE = DocumentTable(
    id="rules", paths=["docs/rule/*.yaml"], schema_path="schemas/rule.schema.yaml"
)
# 行のある a.md・行の無い b.md・範囲の外の tmp/x.md を持つ配信元のファイル
SOURCE_FILES = {
    "project-index.yaml": "name: sample\n",
    "docs/files.yml": "files:\n  - path: a.md\n",
    "docs/a.md": "# a\n",
    "docs/b.md": "# b\n",
    "docs/rule/doc-1.yaml": "id: doc-1\nname: 文書 1\n",
    "tmp/x.md": "# x\n",
}


@pytest.fixture
def prompts() -> PromptSet:
    """同梱した通知の文面のプロンプトを読んだ一式を返す。"""
    return load_prompts(DEFAULT_PROMPTS_DIR, required=[NOTICE_PROMPT_ID])


@pytest.fixture
def make_plain_source(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> Callable[..., ServedSource]:
    """Git でない一時ディレクトリの配信元を作る関数を返す。"""

    def _make(
        *, extra_files: dict[str, str] | None = None, tables: list[DocumentTable] | None = None
    ) -> ServedSource:
        root = tmp_path / "sample"
        write_files(root, {**SOURCE_FILES, **(extra_files or {})})
        config = make_source_config(documents=tables or [FILES_TABLE, RULES_TABLE])
        return make_served_source(root=root, config=config)

    return _make


def test_judge_post_write(
    make_plain_source: Callable[..., ServedSource], prompts: PromptSet
) -> None:
    """行のあるファイルの通知を 1 回だけ返す（正常系）。"""
    # 準備
    source = make_plain_source()
    notified = NotifiedStore()
    request = PostWriteRequest(session_id="s1", paths=[str(source.root / "docs/a.md")])
    # 実行
    first = judge_post_write(request, sources=[source], notified=notified, prompts=prompts)
    second = judge_post_write(request, sources=[source], notified=notified, prompts=prompts)
    # 検証
    assert [notice.action for notice in first.notices] == ["update_row"]
    assert first.additional_context != ""
    assert second.notices == []
    assert second.additional_context == ""


def test_judge_post_write_when_aliases_and_rule_index(
    make_plain_source: Callable[..., ServedSource], prompts: PromptSet
) -> None:
    """エイリアスとルールの索引の行を足す（正常系）。"""
    # 準備
    terms = DocumentTable(
        id="terms",
        paths=["docs/glossary/*.yaml"],
        schema_path="schemas/glossary.schema.yaml",
        records="terms",
        alias_type="term",
    )
    source = make_plain_source(
        extra_files={"rules.yaml": "rules: []\n"}, tables=[FILES_TABLE, RULES_TABLE, terms]
    )
    request = PostWriteRequest(session_id="s1", paths=[str(source.root / "docs/a.md")])
    # 実行
    result = judge_post_write(request, sources=[source], notified=NotifiedStore(), prompts=prompts)
    # 検証
    assert "エイリアス" in result.additional_context
    assert "rules.yaml" in result.additional_context


def test_judge_post_write_when_not_notified(
    make_plain_source: Callable[..., ServedSource], prompts: PromptSet, tmp_path: Path
) -> None:
    """対象外のパスは記録しない（正常系）。"""
    # 準備
    source = make_plain_source()
    notified = NotifiedStore()
    outside = tmp_path / "outside.md"
    outside.write_text("# outside\n", encoding="utf-8")
    skipped = PostWriteRequest(
        session_id="s1", paths=[str(source.root / "docs/files.yml"), str(outside)]
    )
    target = PostWriteRequest(session_id="s1", paths=[str(source.root / "docs/a.md")])
    # 実行
    first = judge_post_write(skipped, sources=[source], notified=notified, prompts=prompts)
    second = judge_post_write(target, sources=[source], notified=notified, prompts=prompts)
    # 検証
    assert first.notices == []
    assert [notice.path for notice in second.notices] == [str(source.root / "docs/a.md")]


def test_classify_path_when_row(make_plain_source: Callable[..., ServedSource]) -> None:
    """行のあるファイル（正常系）。"""
    # 準備
    source = make_plain_source()
    # 実行
    result = classify_path(source.root / "docs/a.md", [source])
    # 検証
    assert result is not None
    assert result.action == "update_row"
    assert result.files_yaml == "docs/files.yml"
    assert result.source == "sample"


def test_classify_path_when_no_row(make_plain_source: Callable[..., ServedSource]) -> None:
    """行の無いファイル（正常系）。"""
    # 準備
    source = make_plain_source()
    # 実行
    result = classify_path(source.root / "docs/b.md", [source])
    # 検証
    assert result is not None
    assert result.action == "add_row"
    assert result.files_yaml == "docs/files.yml"


def test_classify_path_when_worktree(
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> None:
    """ワークツリーのファイル（正常系）。"""
    # 準備
    root = git_repo(SOURCE_FILES)
    run_git(root, "worktree", "add", "-b", "x", ".claude/worktrees/x")
    source = make_served_source(
        root=root,
        config=make_source_config(documents=[FILES_TABLE, RULES_TABLE]),
        is_git=True,
        repo_root=root,
        worktree_globs=[f"{root}/.claude/worktrees/*"],
    )
    # 実行
    result = classify_path(root / ".claude/worktrees/x/docs/a.md", [source])
    # 検証
    assert result is not None
    assert result.action == "update_row"
    assert result.files_yaml == "docs/files.yml"


@pytest.mark.parametrize(
    "relative",
    [
        pytest.param("docs/files.yml", id="files_yaml"),
        pytest.param("project-index.yaml", id="source_config"),
        pytest.param("docs/rule/doc-1.yaml", id="yaml_document"),
        pytest.param("tmp/x.md", id="out_of_range"),
        pytest.param("../outside.md", id="outside_source"),
    ],
)
def test_classify_path_when_not_target(
    make_plain_source: Callable[..., ServedSource], relative: str
) -> None:
    """対象外のパス（正常系）。"""
    # 準備
    source = make_plain_source(extra_files={"../outside.md": "# outside\n"})
    # 実行
    result = classify_path((source.root / relative).resolve(), [source])
    # 検証
    assert result is None


def test_classify_path_when_worktree_of_subfolder(
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> None:
    """リポジトリの下のフォルダが配信元のワークツリー（正常系）。"""
    # 準備
    repo = git_repo(
        {
            "docs/project-index.yaml": "name: sample\n",
            "docs/guide/files.yml": "files:\n  - path: a.md\n",
            "docs/guide/a.md": "# a\n",
        }
    )
    run_git(repo, "worktree", "add", "-b", "x", ".claude/worktrees/x")
    guide = DocumentTable(
        id="guide",
        paths=["guide/files.yml"],
        schema_path="schemas/files.schema.yaml",
        records="files",
        body_file="path",
    )
    source = make_served_source(
        root=repo / "docs",
        config_files=[repo / "docs/project-index.yaml"],
        config=make_source_config(documents=[guide]),
        is_git=True,
        repo_root=repo,
        worktree_globs=[f"{repo}/.claude/worktrees/*"],
    )
    # 実行
    result = classify_path(repo / ".claude/worktrees/x/docs/guide/a.md", [source])
    # 検証
    assert result is not None
    assert result.action == "update_row"
    assert result.files_yaml == "guide/files.yml"


@pytest.mark.parametrize(
    "relative",
    [
        pytest.param("docs/x.yaml", id="other_table"),
        pytest.param("docs/out.log", id="git_ignored"),
    ],
)
def test_classify_path_when_other_table_or_ignored(
    git_repo: Callable[..., Path],
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
    relative: str,
) -> None:
    """ほかの行の文書と Git が無視するファイルは対象外（正常系）。"""
    # 準備
    files: dict[str, Any] = {
        "project-index.yaml": "name: sample\n",
        ".gitignore": "*.log\n",
        "files.yml": "files: []\n",
        "docs/x.yaml": "id: x\nname: x\n",
    }
    root = git_repo(files)
    (root / "docs/out.log").write_text("log\n", encoding="utf-8")
    everything = DocumentTable(
        id="files",
        paths=["files.yml"],
        schema_path="schemas/files.schema.yaml",
        records="files",
        body_file="path",
    )
    yaml_docs = DocumentTable(
        id="docs", paths=["docs/*.yaml"], schema_path="schemas/rule.schema.yaml"
    )
    source = make_served_source(
        root=root,
        config=make_source_config(documents=[everything, yaml_docs]),
        is_git=True,
        repo_root=root,
    )
    # 実行
    result = classify_path(root / relative, [source])
    # 検証
    assert result is None

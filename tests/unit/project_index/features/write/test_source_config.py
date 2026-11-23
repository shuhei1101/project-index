"""書き込みの source_config.py の単体テスト。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.sources.types import DirectCommitConfig
from project_index.features.write.source_config import (
    PROTECTED_KEYS,
    check_source_config_content,
    check_source_config_permitted,
    protected_key_violations,
    read_source_config_file,
    source_config_relative_path,
)
from project_index.shared.errors import (
    SourceConfigNotPermittedError,
    SourceConfigSplitError,
    ValidationFailedError,
)
from project_index.shared.hashing import content_hash

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.sources.types import ServedSource, SourceConfig

RULE_SCHEMA = "title: rule\ntype: object\n"
CONFIG_TEXT = (
    "# 配信元の設定\n"
    "name: sample\n"
    "description: 前の説明\n"
    "documents:\n"
    "  - id: rules\n"
    "    paths: [docs/rule/*.yaml]\n"
    "    schema: schemas/rule.schema.yaml\n"
    "generators:\n"
    "  - id: index\n"
    "    run: [python3, scripts/index.py]\n"
)


def _source(
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
    *,
    config: bool = True,
    write_api_config: bool = True,
    **overrides: Any,
) -> ServedSource:
    """配信元の設定の直コミットの許可を持つ配信元を作る。"""
    direct_commit = DirectCommitConfig(branch="develop", kinds=[], config=config)
    return make_served_source(
        config=make_source_config(direct_commit=direct_commit),
        direct_commit_write_api_config=write_api_config,
        **overrides,
    )


def test_check_source_config_permitted(
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> None:
    """両方で許可している（正常系）。"""
    # 準備
    source = _source(make_served_source, make_source_config)
    # 実行
    result = check_source_config_permitted(source)
    # 検証
    assert result is None


def test_check_source_config_permitted_when_terminal_missing(
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> None:
    """端末の設定で許可していない（異常系）。"""
    # 準備
    source = _source(make_served_source, make_source_config, write_api_config=False)
    # 実行・検証
    with pytest.raises(SourceConfigNotPermittedError, match="sample") as info:
        check_source_config_permitted(source)
    assert info.value.missing == ["write_api_config"]


def test_check_source_config_permitted_when_source_missing(
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> None:
    """配信元の設定で許可していない（異常系）。"""
    # 準備
    source = _source(make_served_source, make_source_config, config=False)
    # 実行・検証
    with pytest.raises(SourceConfigNotPermittedError, match="sample") as info:
        check_source_config_permitted(source)
    assert "direct_commit.config" in info.value.missing


def test_source_config_relative_path(
    make_served_source: Callable[..., ServedSource], tmp_path: Path
) -> None:
    """1 つの project-index.yaml（正常系）。"""
    # 準備
    root = tmp_path / "sample"
    source = make_served_source(root=root, config_files=[root / "project-index.yaml"])
    # 実行
    result = source_config_relative_path(source)
    # 検証
    assert result == "project-index.yaml"


def test_source_config_relative_path_when_split(
    make_served_source: Callable[..., ServedSource], tmp_path: Path
) -> None:
    """2 つのファイルを重ねる（異常系）。"""
    # 準備
    root = tmp_path / "sample"
    source = make_served_source(
        root=root, config_files=[root / "project-index.yaml", tmp_path / "overlay.yaml"]
    )
    # 実行・検証
    with pytest.raises(SourceConfigSplitError, match="sample") as info:
        source_config_relative_path(source)
    assert len(info.value.files) == 2


def test_source_config_relative_path_when_other_name(
    make_served_source: Callable[..., ServedSource], tmp_path: Path
) -> None:
    """別の名前のファイル（異常系）。"""
    # 準備
    root = tmp_path / "sample"
    source = make_served_source(root=root, config_files=[root / "project-index.local.yaml"])
    # 実行・検証
    with pytest.raises(SourceConfigSplitError, match="sample"):
        source_config_relative_path(source)


def test_read_source_config_file(
    tmp_path: Path,
    run_git: Callable[..., str],
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> None:
    """コメントを含む内容をそのまま返す（正常系）。"""
    # 準備
    clone = tmp_path / "clone"
    clone.mkdir()
    run_git(clone, "init", "-b", "main")
    (clone / "project-index.yaml").write_text(CONFIG_TEXT, encoding="utf-8")
    run_git(clone, "add", ".")
    run_git(clone, "commit", "-m", "配信元の設定を追加する")
    develop = clone / ".claude" / "worktrees" / "develop"
    run_git(clone, "worktree", "add", "-b", "develop", str(develop))
    source = _source(
        make_served_source,
        make_source_config,
        root=clone,
        config_files=[clone / "project-index.yaml"],
        is_git=True,
        repo_root=clone,
        storage="git",
        worktree_globs=[str(clone / ".claude" / "worktrees" / "*")],
    )
    # 実行
    result = read_source_config_file(source)
    # 検証
    assert result.content == CONFIG_TEXT
    assert result.version == content_hash(CONFIG_TEXT)
    assert result.branch == "develop"
    assert result.protected_keys == list(PROTECTED_KEYS)


def test_protected_key_violations() -> None:
    """書き換えられるキーだけが変わる（正常系）。"""
    # 準備
    before = {"name": "sample", "nav": {"tabs": [{"title": "前"}]}}
    after = {"name": "sample", "nav": {"tabs": [{"title": "後"}]}}
    # 実行
    result = protected_key_violations(before, after)
    # 検証
    assert result == []


def test_protected_key_violations_when_generators() -> None:
    """コマンドを変える（異常系）。"""
    # 準備
    before = {"generators": [{"id": "index", "run": ["python3", "a.py"]}]}
    after = {"generators": [{"id": "index", "run": ["sh", "-c", "rm -rf /"]}]}
    # 実行
    result = protected_key_violations(before, after)
    # 検証
    assert [(item.path, item.rule) for item in result] == [
        ("sourceConfig.generators", "protected_key")
    ]


def test_protected_key_violations_when_added() -> None:
    """無かったキーを加える（異常系）。"""
    # 準備
    before = {"name": "sample"}
    after = {"name": "sample", "worktrees": ["./other/*"]}
    # 実行
    result = protected_key_violations(before, after)
    # 検証
    assert [(item.path, item.rule) for item in result] == [
        ("sourceConfig.worktrees", "protected_key")
    ]


@pytest.fixture
def config_root(tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]) -> Path:
    """スキーマのファイルを持つ配信元のフォルダを返す。"""
    root = tmp_path / "root"
    write_files(root, {"schemas/rule.schema.yaml": RULE_SCHEMA})
    return root


def test_check_source_config_content(config_root: Path) -> None:
    """説明だけを変える（正常系）。"""
    # 準備
    content = CONFIG_TEXT.replace("前の説明", "後の説明")
    # 実行
    result = check_source_config_content(content, current=CONFIG_TEXT, root=config_root)
    # 検証
    assert result["description"] == "後の説明"


def test_check_source_config_content_when_invalid(config_root: Path) -> None:
    """スキーマに合格しない（異常系）。"""
    # 準備
    content = CONFIG_TEXT.replace("    paths: [docs/rule/*.yaml]\n", "")
    # 実行・検証
    with pytest.raises(ValidationFailedError, match="配信元の設定") as info:
        check_source_config_content(content, current=CONFIG_TEXT, root=config_root)
    assert info.value.violations[0].path.startswith("sourceConfig.documents[0]")


def test_check_source_config_content_when_not_yaml(config_root: Path) -> None:
    """YAML として読めない（異常系）。"""
    # 準備
    content = "- マップでない\n"
    # 実行・検証
    with pytest.raises(ValidationFailedError, match="配信元の設定") as info:
        check_source_config_content(content, current=CONFIG_TEXT, root=config_root)
    assert [item.path for item in info.value.violations] == ["sourceConfig.content"]

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.sources import service as service_module
from project_index.features.sources.service import (
    assemble_source,
    check_scripts,
    compare_config_version,
    entry_source_id,
    load_source,
    load_source_at,
    validate_source_config,
)
from project_index.features.sources.types import ScriptEntry, ServedSource, SourceConfig
from project_index.shared.errors import ValidationFailedError, Violation

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.settings.types import SourceEntry

RULE_SCHEMA = "title: rule\ntype: object\n"


def _config_value(**overrides: Any) -> dict[str, Any]:
    """検証を通る最小の配信元の設定の値を返す。"""
    value: dict[str, Any] = {
        "name": "sample",
        "documents": [
            {
                "id": "rules",
                "paths": ["docs/rule/*.yaml"],
                "schema": "schemas/rule.schema.yaml",
            }
        ],
    }
    value.update(overrides)
    return value


@pytest.fixture
def source_root(tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]) -> Path:
    """スキーマのファイルを持つ配信元のフォルダを返す。"""
    root = tmp_path / "root"
    write_files(root, {"schemas/rule.schema.yaml": RULE_SCHEMA})
    return root


def test_validate_source_config(source_root: Path) -> None:
    """違反が無い（正常系）。"""
    # 準備
    value = _config_value()
    # 実行
    result = validate_source_config(value, root=source_root)
    # 検証
    assert result == []


def test_validate_source_config_when_required_missing(source_root: Path) -> None:
    """必須のキーが無い（正常系）。"""
    # 準備
    value = _config_value(documents=[{"id": "rules", "schema": "schemas/rule.schema.yaml"}])
    # 実行
    result = validate_source_config(value, root=source_root)
    # 検証
    assert result == [Violation(path="documents[0].paths", rule="必須のキーが無い")]


def test_validate_source_config_when_unknown_key(source_root: Path) -> None:
    """表に無いキー（正常系）。"""
    # 準備
    value = _config_value(mcp={})
    # 実行
    result = validate_source_config(value, root=source_root)
    # 検証
    assert [(v.path, v.rule) for v in result] == [("mcp", "知らないキー")]


def test_validate_source_config_when_duplicate_id(source_root: Path) -> None:
    """行の ID が重なる（正常系）。"""
    # 準備
    row = {
        "id": "a",
        "paths": ["docs/*.yaml"],
        "schema": "schemas/rule.schema.yaml",
    }
    value = _config_value(documents=[row, dict(row)])
    # 実行
    result = validate_source_config(value, root=source_root)
    # 検証
    assert [v.path for v in result] == ["documents[1].id"]


def test_validate_source_config_when_dangling_reference(source_root: Path) -> None:
    """無い ID を指す（正常系）。"""
    # 準備
    row = {
        "id": "rules",
        "paths": ["docs/*.yaml"],
        "schema": "schemas/rule.schema.yaml",
        "validators": ["nope"],
    }
    value = _config_value(documents=[row], validators=[])
    # 実行
    result = validate_source_config(value, root=source_root)
    # 検証
    assert [(v.path, v.rule) for v in result] == [("documents[0].validators[0]", "存在しない ID")]


def test_validate_source_config_when_schema_missing(source_root: Path) -> None:
    """スキーマのファイルが無い（正常系）。"""
    # 準備
    row = {"id": "rules", "paths": ["docs/*.yaml"], "schema": "schemas/none.yaml"}
    value = _config_value(documents=[row])
    # 実行
    result = validate_source_config(value, root=source_root)
    # 検証
    assert [v.path for v in result] == ["documents[0].schema"]


def test_validate_source_config_when_schema_broken(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """スキーマのファイルを YAML として読み込めない（正常系）。"""
    # 準備
    root = tmp_path / "root"
    write_files(root, {"schemas/rule.schema.yaml": "a: [\n"})
    value = _config_value()
    # 実行
    result = validate_source_config(value, root=root)
    # 検証
    assert [v.path for v in result] == ["documents[0].schema"]
    assert result[0].rule.startswith("スキーマを YAML として読み込めない:")


def test_validate_source_config_when_body_file_without_records(source_root: Path) -> None:
    """`records` の無い行が `body_file` を持つ（正常系）。"""
    # 準備
    row = {
        "id": "rules",
        "paths": ["docs/rule/*.yaml"],
        "schema": "schemas/rule.schema.yaml",
        "body_file": "body",
    }
    value = _config_value(documents=[row])
    # 実行
    result = validate_source_config(value, root=source_root)
    # 検証
    assert [(v.path, v.rule) for v in result] == [
        ("documents[0].body_file", "records と一緒に記載してください")
    ]


def test_validate_source_config_when_outside_root(source_root: Path) -> None:
    """配信元の外を指す（正常系）。"""
    # 準備
    row = {
        "id": "rules",
        "paths": ["../x/*.md"],
        "schema": "schemas/rule.schema.yaml",
    }
    value = _config_value(documents=[row])
    # 実行
    result = validate_source_config(value, root=source_root)
    # 検証
    assert [v.path for v in result] == ["documents[0].paths[0]"]


def test_validate_source_config_when_exclude_has_slash(source_root: Path) -> None:
    """除外の名前に `/` を含む（正常系）。"""
    # 準備
    row = {
        "id": "rules",
        "paths": ["docs/rule/*.yaml"],
        "schema": "schemas/rule.schema.yaml",
        "exclude": ["a/README.md"],
    }
    value = _config_value(documents=[row])
    # 実行
    result = validate_source_config(value, root=source_root)
    # 検証
    assert [v.path for v in result] == ["documents[0].exclude[0]"]


def test_validate_source_config_when_legacy_keys(source_root: Path) -> None:
    """前の形式のキー（正常系）。"""
    # 準備
    row = {
        "id": "rules",
        "type": "yaml",
        "paths": ["docs/rule/*.yaml"],
        "schema": "schemas/rule.schema.yaml",
        "defaults": [{"paths": ["a/**"], "tags": ["x"]}],
        "metadata": {"name": {"type": "ref", "field": "title"}},
    }
    value = _config_value(documents=[row])
    # 実行
    result = validate_source_config(value, root=source_root)
    # 検証
    by_path = {v.path: v.rule for v in result}
    assert by_path["documents[0].type"] == "知らないキー"
    assert by_path["documents[0].defaults"] == "知らないキー"
    assert "documents[0].metadata.name" in by_path


def test_validate_source_config_when_tag_master(
    source_root: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """タグのマスターを書いた（正常系）。"""
    # 準備
    write_files(source_root, {"tags.yaml": "python: Python の規約\n"})
    value = _config_value(tags="tags.yaml")
    # 実行
    result = validate_source_config(value, root=source_root)
    # 検証
    assert [(v.path, v.rule) for v in result] == [("tags", "知らないキー")]


def test_check_scripts(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
) -> None:
    """全て実行できる（正常系）。"""
    # 準備
    write_files(tmp_path, {"scripts/c.py": "print('x')\n"})
    config = make_source_config(converters=[ScriptEntry(id="c", run=["python3", "scripts/c.py"])])
    # 実行
    result = check_scripts(config, root=tmp_path)
    # 検証
    assert result == []


def test_check_scripts_when_missing(
    tmp_path: Path, make_source_config: Callable[..., SourceConfig]
) -> None:
    """スクリプトが無い（正常系）。"""
    # 準備
    config = make_source_config(
        converters=[ScriptEntry(id="c", run=["python3", "scripts/none.py"])]
    )
    # 実行
    result = check_scripts(config, root=tmp_path)
    # 検証
    assert [v.path for v in result] == ["converters[0]"]
    assert "scripts/none.py" in result[0].rule


def test_compare_config_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """同じ・古い・新しい（正常系）。"""
    # 準備
    monkeypatch.setattr(service_module, "SOURCE_CONFIG_VERSION", "2")
    # 実行
    same = compare_config_version("2")
    older = compare_config_version("1")
    newer = compare_config_version("3")
    # 検証
    assert (same, older, newer) == ("same", "older", "newer")


@pytest.mark.parametrize(
    ("source_id", "files", "expected"),
    [
        pytest.param("given", {"a.yaml": "name: sample\n"}, "given", id="id"),
        pytest.param(
            None, {"a.yaml": "name: sample\n", "b.yaml": "name: local\n"}, "local", id="name"
        ),
        pytest.param(None, {}, None, id="missing"),
    ],
)
def test_entry_source_id(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_entry: Callable[..., SourceEntry],
    source_id: str | None,
    files: dict[str, str],
    expected: str | None,
) -> None:
    """id か、無ければ重ねた設定の name を返す（正常系）。"""
    # 準備
    write_files(tmp_path, files)
    entry = make_entry([str(tmp_path / "a.yaml"), str(tmp_path / "b.yaml")], source_id=source_id)
    # 実行・検証
    assert entry_source_id(entry) == expected


def test_load_source(
    git_repo: Callable[..., Path],
    sample_files: dict[str, str],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """配信する（正常系）。"""
    # 準備
    root = git_repo(sample_files)
    entry = make_entry(str(root / "project-index.yaml"))
    # 実行
    served, status = load_source(entry, index=0)
    # 検証
    assert served is not None
    assert served.id == "sample"
    assert served.is_git is True
    assert "rules" in served.schemas
    assert status.status == "serving"


def test_load_source_when_merged(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    sample_files: dict[str, str],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """複数の YAML を重ねる（正常系）。"""
    # 準備
    root = tmp_path / "ws"
    write_files(root, sample_files)
    write_files(tmp_path / "local", {"local.yaml": "description: 後の値\n"})
    entry = make_entry([str(root / "project-index.yaml"), str(tmp_path / "local" / "local.yaml")])
    # 実行
    served, _ = load_source(entry, index=0)
    # 検証
    assert served is not None
    assert served.config.description == "後の値"
    assert served.root == root


def test_load_source_when_disabled(make_entry: Callable[..., SourceEntry]) -> None:
    """端末の設定で無効（正常系）。"""
    # 準備
    entry = make_entry("/tmp/none/project-index.yaml", source_id="a", enabled=False)
    # 実行
    served, status = load_source(entry, index=0)
    # 検証
    assert served is None
    assert status.status == "disabled"


def test_load_source_when_config_missing(make_entry: Callable[..., SourceEntry]) -> None:
    """設定のファイルが無い（正常系）。"""
    # 準備
    entry = make_entry("/tmp/none.yaml", source_id="a")
    # 実行
    served, status = load_source(entry, index=0)
    # 検証
    assert served is None
    assert status.status == "not_served"
    assert [error.path for error in status.errors] == ["config[0]"]


def test_load_source_when_config_broken(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """設定のファイルを YAML として読み込めない（正常系）。"""
    # 準備
    write_files(tmp_path, {"project-index.yaml": "name: [\n"})
    entry = make_entry(str(tmp_path / "project-index.yaml"), source_id="sample")
    # 実行
    served, status = load_source(entry, index=0)
    # 検証
    assert served is None
    assert status.status == "not_served"
    assert [error.path for error in status.errors] == ["config[0]"]
    assert status.errors[0].rule.startswith("YAML として読み込めない:")


def test_load_source_when_invalid(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_entry: Callable[..., SourceEntry],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """検証に失敗する（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "project-index.yaml": "name: sample\ndocuments:\n  - id: rules\n    schema: schemas/rule.schema.yaml\n"
        },
    )
    entry = make_entry(str(tmp_path / "project-index.yaml"), source_id="sample")
    # 実行
    with caplog.at_level(logging.ERROR):
        served, status = load_source(entry, index=0)
    # 検証
    assert served is None
    assert status.status == "not_served"
    assert [error.path for error in status.errors] == ["documents[0].paths"]
    assert "sample: documents[0].paths: 必須のキーが無い" in caplog.text


def test_load_source_when_script_missing(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    sample_files: dict[str, str],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """スクリプトが無い（正常系）。"""
    # 準備
    config = (
        sample_files["project-index.yaml"]
        + "converters:\n  - id: c\n    run: [python3, scripts/none.py]\n"
    )
    write_files(tmp_path, {**sample_files, "project-index.yaml": config})
    entry = make_entry(str(tmp_path / "project-index.yaml"), source_id="sample")
    # 実行
    served, status = load_source(entry, index=0)
    # 検証
    assert served is None
    assert status.status == "not_served"
    assert [error.path for error in status.errors] == ["converters[0]"]


def test_load_source_when_version_old(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_files: Callable[[Path, dict[str, str]], None],
    sample_files: dict[str, str],
    make_entry: Callable[..., SourceEntry],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """設定のバージョンが古い（正常系）。"""
    # 準備
    monkeypatch.setattr(service_module, "SOURCE_CONFIG_VERSION", "2")
    write_files(
        tmp_path,
        {
            **sample_files,
            "project-index.yaml": 'version: "1"\n' + sample_files["project-index.yaml"],
        },
    )
    entry = make_entry(str(tmp_path / "project-index.yaml"), source_id="sample")
    # 実行
    with caplog.at_level(logging.WARNING):
        served, status = load_source(entry, index=0)
    # 検証
    assert served is not None
    assert status.status == "serving"
    assert status.config_version == ("1", "2")
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_load_source_when_legacy(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    sample_files: dict[str, str],
    make_entry: Callable[..., SourceEntry],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """前の形式の設定（正常系）。"""
    # 準備
    legacy = (
        'version: "1"\n'
        "name: sample\n"
        "documents:\n"
        "  - id: rules\n"
        "    type: markdown\n"
        "    paths: [docs/rule/*.yaml]\n"
        "    schema: schemas/rule.schema.yaml\n"
    )
    write_files(tmp_path, {**sample_files, "project-index.yaml": legacy})
    entry = make_entry(str(tmp_path / "project-index.yaml"), source_id="sample")
    # 実行
    with caplog.at_level(logging.ERROR):
        served, status = load_source(entry, index=0)
    # 検証
    assert served is None
    assert status.status == "not_served"
    assert [error.path for error in status.errors] == ["documents[0].type"]
    assert "project-index migrate --source" in caplog.text
    assert str(tmp_path / "project-index.yaml") in caplog.text


def test_load_source_when_not_git(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    sample_files: dict[str, str],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """Git の管理外のフォルダ（正常系）。"""
    # 準備
    write_files(tmp_path / "plain", sample_files)
    entry = make_entry(str(tmp_path / "plain" / "project-index.yaml"))
    # 実行
    served, _ = load_source(entry, index=0)
    # 検証
    assert served is not None
    assert served.is_git is False
    assert served.repo_root is None


@pytest.fixture
def cloned_source(
    git_repo: Callable[..., Path],
    sample_files: dict[str, str],
    make_served_source: Callable[..., ServedSource],
) -> ServedSource:
    """git リポジトリのクローン本体の配信元を返す。"""
    root = git_repo(sample_files)
    return make_served_source(
        id="sample",
        root=root,
        config_files=[root / "project-index.yaml"],
        is_git=True,
        repo_root=root,
    )


@pytest.fixture
def worktree(cloned_source: ServedSource, run_git: Callable[..., str], tmp_path: Path) -> Path:
    """クローン本体のワークツリーを作って返す。"""
    path = tmp_path / "wt"
    run_git(cloned_source.root, "worktree", "add", "-b", "feat/x", str(path))
    return path


def test_load_source_at(
    cloned_source: ServedSource,
    worktree: Path,
    sample_files: dict[str, str],
) -> None:
    """ワークツリーの設定（正常系）。"""
    # 準備
    extra = "  - id: notes\n    paths: [docs/note/*.yaml]\n    schema: schemas/rule.schema.yaml\n"
    (worktree / "project-index.yaml").write_text(
        sample_files["project-index.yaml"] + extra, encoding="utf-8"
    )
    # 実行
    result = load_source_at(cloned_source, worktree)
    # 検証
    assert [row.id for row in result.config.documents] == ["rules", "notes"]
    assert result.root == worktree
    assert result.id == "sample"


def test_load_source_at_when_config_missing(cloned_source: ServedSource, worktree: Path) -> None:
    """設定のファイルが無い（異常系）。"""
    # 準備
    (worktree / "project-index.yaml").unlink()
    # 実行・検証
    with pytest.raises(ValidationFailedError) as exc_info:
        load_source_at(cloned_source, worktree)
    assert [v.path for v in exc_info.value.violations] == ["config[0]"]


def test_load_source_at_when_ignored_config(
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    sample_files: dict[str, str],
    make_served_source: Callable[..., ServedSource],
    tmp_path: Path,
) -> None:
    """無視した先頭の設定はクローン本体のものを使う（正常系）。"""
    # 準備
    files = {k: v for k, v in sample_files.items() if k != "project-index.yaml"}
    root = git_repo({**files, ".gitignore": "project-index.local.yaml\n"})
    local = root / "project-index.local.yaml"
    local.write_text(sample_files["project-index.yaml"], encoding="utf-8")
    source = make_served_source(
        id="sample", root=root, config_files=[local], is_git=True, repo_root=root
    )
    path = tmp_path / "wt"
    run_git(root, "worktree", "add", "-b", "feat/x", str(path))
    # 実行
    result = load_source_at(source, path)
    # 検証
    assert result.config_files[0] == local
    assert result.root == path


def test_load_source_at_when_invalid(cloned_source: ServedSource, worktree: Path) -> None:
    """検証に通らない（異常系）。"""
    # 準備
    (worktree / "project-index.yaml").write_text(
        "name: sample\ndocuments:\n  - id: rules\n    schema: schemas/rule.schema.yaml\n",
        encoding="utf-8",
    )
    # 実行・検証
    with pytest.raises(ValidationFailedError) as exc_info:
        load_source_at(cloned_source, worktree)
    assert [v.path for v in exc_info.value.violations] == ["documents[0].paths"]


def test_assemble_source(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    sample_files: dict[str, str],
) -> None:
    """`root_override` のフォルダを配信元のフォルダにする（正常系）。"""
    # 準備
    root = tmp_path / "root"
    write_files(
        root, {key: value for key, value in sample_files.items() if key != "project-index.yaml"}
    )
    config_dir = tmp_path / "cfg"
    write_files(config_dir, {"project-index.yaml": sample_files["project-index.yaml"]})
    # 実行
    served, config, violations = assemble_source(
        [config_dir / "project-index.yaml"],
        source_id=None,
        scope_read=[],
        scope_write=None,
        root_override=root,
    )
    # 検証
    assert served is not None
    assert config is not None
    assert served.root == root
    assert violations == []


def test_assemble_source_when_script_missing(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    sample_files: dict[str, str],
) -> None:
    """スクリプトの確かめの失敗は設定を残す（正常系）。"""
    # 準備
    config_text = (
        sample_files["project-index.yaml"]
        + "converters:\n  - id: conv\n    run: [python3, scripts/none.py]\n"
    )
    write_files(tmp_path, {**sample_files, "project-index.yaml": config_text})
    # 実行
    served, config, violations = assemble_source(
        [tmp_path / "project-index.yaml"], source_id=None, scope_read=[], scope_write=None
    )
    # 検証
    assert served is None
    assert config is not None
    assert len(violations) == 1


def test_source_schema_json() -> None:
    """配布のファイルと一致する（正常系）。"""
    # 準備
    from project_index.features.sources.service import source_schema_json

    distributed = Path(__file__).resolve().parents[5] / "schemas" / "project-index.schema.json"
    command = (
        'uv run python -c "from project_index.features.sources.service import source_schema_json; '
        "print(source_schema_json(), end='')\" > schemas/project-index.schema.json"
    )
    # 実行
    result = source_schema_json()
    # 検証
    assert result == distributed.read_text(encoding="utf-8"), (
        f"schemas/project-index.schema.json が正本のスキーマとずれています。書き直すには: {command}"
    )


def test_source_schema_json_when_metadata() -> None:
    """新しい形式の documents の行（正常系）。"""
    # 準備
    from project_index.features.sources.service import source_schema_json

    schema = json.loads(source_schema_json())
    # 実行
    row = schema["properties"]["documents"]["items"]
    # 検証
    assert "type" not in row["properties"]
    assert "defaults" not in row["properties"]
    assert row["properties"]["metadata"]["additionalProperties"]["type"] == "string"
    assert row["properties"]["alias_type"]["enum"] == [
        "term",
        "doc",
        "command",
        "url",
        "skill",
        "tool",
        "path",
        "env",
        "avoid",
    ]
    assert row["required"] == ["id", "paths", "schema"]


KIND_A_ROW = "  - id: kind_a\n    paths: [docs/a/*.yaml]\n    schema: schemas/a.schema.yaml\n"


@pytest.fixture
def develop_ahead(
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    commit_all: Callable[..., str],
    sample_files: dict[str, str],
) -> tuple[Path, str]:
    """`develop` にだけ `kind_a` の行とスキーマを commit し、`master` を checkout したクローンと `develop` の commit を返す。"""
    root = git_repo(sample_files)
    run_git(root, "branch", "master")
    develop = commit_all(
        root,
        {
            "project-index.yaml": sample_files["project-index.yaml"] + KIND_A_ROW,
            "schemas/a.schema.yaml": RULE_SCHEMA,
        },
    )
    run_git(root, "checkout", "master")
    return root, develop


def test_validate_source_config_when_nav_filter(source_root: Path) -> None:
    """nav の auto の条件（正常系）。"""
    # 準備
    valid = _config_value(
        nav={
            "tabs": [
                {
                    "title": "mcp",
                    "items": [
                        {"auto": {"filter": {"field": "tags", "op": "eq", "values": ["mcp"]}}}
                    ],
                }
            ]
        }
    )
    invalid = _config_value(
        nav={
            "tabs": [
                {
                    "title": "mcp",
                    "items": [
                        {"auto": {"filter": {"field": "tags", "op": "like", "values": ["mcp"]}}}
                    ],
                }
            ]
        }
    )
    # 実行
    results = [
        validate_source_config(valid, root=source_root),
        validate_source_config(invalid, root=source_root),
    ]
    # 検証
    assert results[0] == []
    assert len(results[1]) >= 1
    assert results[1][0].path.startswith("nav.tabs[0].items[0].auto.filter")


def test_validate_source_config_when_cache_outside_converters(source_root: Path) -> None:
    """converters 以外の行の cache（異常系）。"""
    # 準備
    value = _config_value(
        validators=[{"id": "v", "run": ["python3", "scripts/v.py"], "cache": False}]
    )
    # 実行
    result = validate_source_config(value, root=source_root)
    # 検証
    assert [violation.path for violation in result] == ["validators[0].cache"]


def test_load_source_when_default_ref(
    develop_ahead: tuple[Path, str], make_entry: Callable[..., SourceEntry]
) -> None:
    """default_ref の設定とスキーマで組み立てる（正常系）。"""
    # 準備
    root, develop = develop_ahead
    entry = make_entry(str(root / "project-index.yaml"))
    # 実行
    served, status = load_source(entry, index=0)
    # 検証
    assert status.status == "serving"
    assert served is not None
    assert [table.id for table in served.config.documents] == ["rules", "kind_a"]
    assert "kind_a" in served.schemas
    assert served.config_commit == develop


def test_load_source_when_worktree_config(
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    sample_files: dict[str, str],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """ワークツリーの設定でもメインから数える（正常系）。"""
    # 準備
    files = {
        **sample_files,
        "project-index.yaml": sample_files["project-index.yaml"]
        + "worktrees: [.claude/worktrees/*]\n",
    }
    root = git_repo(files, branch="main")
    worktree = root / ".claude/worktrees/develop"
    run_git(root, "worktree", "add", "-b", "develop", str(worktree))
    entry = make_entry(str(worktree / "project-index.yaml"))
    # 実行
    served, _ = load_source(entry, index=0)
    # 検証
    assert served is not None
    assert served.worktree_globs == [str(root.resolve() / ".claude/worktrees/*")]


def test_load_source_when_converter_cache(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    sample_files: dict[str, str],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """converters の行の cache を読む（正常系）。"""
    # 準備
    config = (
        sample_files["project-index.yaml"]
        + "converters:\n"
        + "  - id: c1\n    run: [python3, scripts/c.py]\n    cache: false\n"
        + "  - id: c2\n    run: [python3, scripts/c.py]\n"
    )
    write_files(
        tmp_path, {**sample_files, "project-index.yaml": config, "scripts/c.py": "print('# c')\n"}
    )
    entry = make_entry(str(tmp_path / "project-index.yaml"), source_id="sample")
    # 実行
    served, status = load_source(entry, index=0)
    # 検証
    assert status.status == "serving"
    assert served is not None
    assert served.script("converters", "c1").cache is False
    assert served.script("converters", "c2").cache is True


def test_read_default_ref_config(develop_ahead: tuple[Path, str]) -> None:
    """別のブランチを checkout していても default_ref を読む（正常系）。"""
    from project_index.features.sources.service import read_default_ref_config

    # 準備
    root, develop = develop_ahead
    # 実行
    result = read_default_ref_config(root / "project-index.yaml")
    # 検証
    assert result is not None
    assert result[0] == develop
    assert "id: kind_a" in result[1]


def test_read_default_ref_config_when_not_git(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    sample_files: dict[str, str],
) -> None:
    """Git の管理外（正常系）。"""
    from project_index.features.sources.service import read_default_ref_config

    # 準備
    write_files(tmp_path / "plain", sample_files)
    # 実行
    result = read_default_ref_config(tmp_path / "plain" / "project-index.yaml")
    # 検証
    assert result is None


def test_read_default_ref_config_when_ref_missing(
    git_repo: Callable[..., Path], sample_files: dict[str, str]
) -> None:
    """default_ref が無い（異常系）。"""
    from project_index.features.sources.service import read_default_ref_config

    # 準備
    files = {
        **sample_files,
        "project-index.yaml": sample_files["project-index.yaml"] + "default_ref: none\n",
    }
    root = git_repo(files)
    # 実行・検証
    with pytest.raises(ValidationFailedError, match="none を解けません") as exc_info:
        read_default_ref_config(root / "project-index.yaml")
    assert [item.path for item in exc_info.value.violations] == ["default_ref"]


def test_read_default_ref_config_when_ignored(
    git_repo: Callable[..., Path], run_git: Callable[..., str], sample_files: dict[str, str]
) -> None:
    """無視されている先頭の設定はディスクから読む（正常系）。"""
    from project_index.features.sources.service import read_default_ref_config

    # 準備
    files = {k: v for k, v in sample_files.items() if k != "project-index.yaml"}
    root = git_repo({**files, ".gitignore": "project-index.local.yaml\n"})
    text = sample_files["project-index.yaml"] + "default_ref: develop\n"
    (root / "project-index.local.yaml").write_text(text, encoding="utf-8")
    develop = run_git(root, "rev-parse", "develop").strip()
    # 実行
    result = read_default_ref_config(root / "project-index.local.yaml")
    # 検証
    assert result == (develop, text)


def test_read_default_ref_config_when_not_committed(
    git_repo: Callable[..., Path], sample_files: dict[str, str]
) -> None:
    """無視していない先頭の設定が default_ref に無い（異常系）。"""
    from project_index.features.sources.service import read_default_ref_config

    # 準備
    files = {k: v for k, v in sample_files.items() if k != "project-index.yaml"}
    root = git_repo(files)
    (root / "project-index.yaml").write_text(sample_files["project-index.yaml"], encoding="utf-8")
    # 実行・検証
    with pytest.raises(
        ValidationFailedError, match=r"develop に project-index\.yaml がありません"
    ) as exc_info:
        read_default_ref_config(root / "project-index.yaml")
    assert [item.path for item in exc_info.value.violations] == ["config[0]"]

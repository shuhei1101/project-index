from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from project_index.features.admin.service import (
    _load_candidate,
    _source_states,
    check_project,
    get_status,
    reload_config,
    try_convert,
    version_state,
)
from project_index.features.admin.types import CheckProjectRequest, TryConvertRequest
from project_index.features.settings.types import SourceEntry, TerminalConfig, TerminalConfigInvalidError
from project_index.features.sources.registry import SourceRegistry
from project_index.main import Handlers, build_handlers
from project_index.shared.errors import (
    ConverterNotDefinedError,
    ConfigNotFoundError,
    ConfigParseError,
    ConvertScriptError,
    DocumentNotFoundError,
    ValidationFailedError,
)
from project_index.shared.yaml_io import load_yaml

BROKEN_CONFIG = "name: {name}\ndocuments:\n  - id: rules\n    schema: schemas/rule.schema.yaml\n"
NOTES_CONFIG = (
    "name: notes\n"
    "documents:\n"
    "  - id: notes\n"
    "    paths: [docs/files.yaml]\n"
    "    schema: schemas/rule.schema.yaml\n"
    "    records: files\n"
    "    body_file: path\n"
)
EMPTY_NOTES_CONFIG = (
    "name: empty\n"
    "documents:\n"
    "  - id: notes\n"
    "    paths: [notes/*.yaml]\n"
    "    schema: schemas/rule.schema.yaml\n"
)
CONVERT_CONFIG = (
    "name: conv\n"
    "documents:\n"
    "  - id: rules\n"
    "    paths: [docs/rule/*.yaml]\n"
    "    schema: schemas/rule.schema.yaml\n"
    "    converter: conv\n"
    "converters:\n"
    "  - id: conv\n"
    "    run: [python3, scripts/convert.py]\n"
)
SCRIPT_MISSING_CONFIG = (
    "name: sample\n"
    "documents:\n"
    "  - id: rules\n"
    "    paths: [docs/rule/*.yaml]\n"
    "    schema: schemas/rule.schema.yaml\n"
    "converters:\n"
    "  - id: conv\n"
    "    run: [python3, scripts/missing.py]\n"
)
RULE_SCHEMA = "title: rule\ntype: object\n"
FILES_ROW_CONFIG = (
    "name: files\n"
    "documents:\n"
    "  - id: docs\n"
    "    paths: [files.yaml]\n"
    "    schema: schemas/files.schema.yaml\n"
    "    records: files\n"
    "    body_file: path\n"
)
FILES_SCHEMA_TEMPLATE = Path(__file__).parents[5] / "templates" / "files.schema.yaml"


def _handlers(
    make_terminal_config: Callable[..., TerminalConfig], *entries: SourceEntry, **overrides: object
) -> Handlers:
    """端末の設定の行から、部品を本物で配線して配信元を読んだ配線済みの関数を作る。"""
    terminal = make_terminal_config(sources=list(entries), **overrides)
    handlers = build_handlers(terminal)
    handlers.reload_sources(terminal)
    return handlers


def test_get_status(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """配信中・検証で外した・無効の配信元を並べる（正常系）。"""
    # 準備
    alpha = make_source_dir("alpha", unindexed=1)
    write_files(tmp_path / "broken", {"project-index.yaml": BROKEN_CONFIG.format(name="broken")})
    off = make_source_dir("off")
    handlers = _handlers(
        make_terminal_config,
        make_entry(str(alpha), source_id="alpha"),
        make_entry(str(tmp_path / "broken" / "project-index.yaml"), source_id="broken"),
        make_entry(str(off), source_id="off", enabled=False),
        port=8790,
    )
    # 実行
    status = get_status(handlers, env={})
    # 検証
    assert status.address == "http://127.0.0.1:8790/"
    assert [(item.id, item.status) for item in status.sources] == [
        ("alpha", "serving"),
        ("broken", "not_served"),
        ("off", "disabled"),
    ]
    assert status.sources[0].sync is not None
    assert status.sources[0].sync.unindexed_files == 1
    assert status.sources[1].sync is None
    assert status.sources[2].sync is None


def test_get_status_when_loading(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_handlers: Callable[..., Any],
) -> None:
    """読み込み中は配信元を待たずに返す（正常系）。"""
    # 準備
    terminal = make_terminal_config(
        sources=[make_entry(str(make_source_dir("alpha")), source_id="alpha")]
    )
    handlers = make_handlers(terminal=terminal, registry=SourceRegistry(loading=True))
    # 実行
    status = get_status(handlers, env={})
    # 検証
    assert status.loading is True
    assert status.sources == []


def test_get_status_when_port_env(
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """PROJECT_INDEX_PORT のポートをアドレスに使う（正常系）。"""
    # 準備
    handlers = _handlers(make_terminal_config)
    # 実行
    status = get_status(handlers, env={"PROJECT_INDEX_PORT": "8799"})
    # 検証
    assert status.address == "http://127.0.0.1:8799/"


def test_reload_config(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_dir: Callable[..., Path],
    write_settings: Callable[..., Path],
    make_real_handlers: Callable[[Path], Handlers],
) -> None:
    """追加・削除・配信していない配信元を返す（正常系）。"""
    # 準備
    paths = {name: make_source_dir(name) for name in ("a", "b", "c")}
    write_files(tmp_path / "d", {"project-index.yaml": BROKEN_CONFIG.format(name="d")})
    paths["d"] = tmp_path / "d" / "project-index.yaml"
    rows = {name: {"id": name, "config": str(path)} for name, path in paths.items()}
    handlers = make_real_handlers(write_settings([rows["a"], rows["b"]]))
    write_settings([rows["b"], rows["c"], rows["d"]])
    # 実行
    result = reload_config(handlers)
    # 検証
    assert result.added == ["c"]
    assert result.removed == ["a"]
    assert [item.id for item in result.not_served] == ["d"]
    assert [item.id for item in result.sources] == ["b", "c", "d"]


def test_reload_config_when_invalid(
    make_source_dir: Callable[..., Path],
    write_settings: Callable[..., Path],
    make_real_handlers: Callable[[Path], Handlers],
) -> None:
    """端末の設定が違反する（異常系）。"""
    # 準備
    row = {"id": "a", "config": str(make_source_dir("a"))}
    handlers = make_real_handlers(write_settings([row]))
    before = handlers.registry.statuses()
    write_settings([row], port="abc")
    # 実行・検証
    with pytest.raises(TerminalConfigInvalidError):
        reload_config(handlers)
    assert handlers.registry.statuses() == before


def test_check_project(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """違反が無い配信元の同期の件数と内訳を返す（正常系）。"""
    # 準備
    config = make_source_dir("alpha", unindexed=1)
    handlers = _handlers(make_terminal_config, make_entry(str(config), source_id="reg"))
    request = CheckProjectRequest(path=str(config.parent))
    # 実行
    result = check_project(request, handlers=handlers)
    # 検証
    assert result.registered_id == "reg"
    assert result.violations == []
    assert result.sync is not None
    assert result.sync.unindexed_files == 1
    assert len(result.sync.items) == 1


def test_check_project_when_violations(
    tmp_path: Path, make_terminal_config: Callable[..., TerminalConfig]
) -> None:
    """違反があれば違反だけを返す（正常系）。"""
    # 準備
    handlers = _handlers(make_terminal_config)
    request = CheckProjectRequest(path=str(tmp_path), config=BROKEN_CONFIG.format(name="broken"))
    # 実行
    result = check_project(request, handlers=handlers)
    # 検証
    assert len(result.violations) >= 1
    assert result.sync is None
    assert result.missing_paths == []
    assert result.script_errors == []


def test_check_project_when_script_missing(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """動かないスクリプトを script_errors に入れる（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "project-index.yaml": SCRIPT_MISSING_CONFIG,
            "schemas/rule.schema.yaml": RULE_SCHEMA,
            "docs/rule/doc-1.yaml": "id: doc-1\n",
        },
    )
    handlers = _handlers(make_terminal_config)
    # 実行
    result = check_project(CheckProjectRequest(path=str(tmp_path)), handlers=handlers)
    # 検証
    assert [item.script for item in result.script_errors] == ["python3 scripts/missing.py"]
    assert result.sync is None


def test_check_project_when_missing_paths(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """当たるファイルが無い範囲を返す（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {"project-index.yaml": EMPTY_NOTES_CONFIG, "schemas/rule.schema.yaml": RULE_SCHEMA},
    )
    (tmp_path / "notes").mkdir()
    handlers = _handlers(make_terminal_config)
    # 実行
    result = check_project(CheckProjectRequest(path=str(tmp_path)), handlers=handlers)
    # 検証
    assert result.missing_paths == ["notes/*.yaml"]


def test_check_project_when_items_over_limit(
    make_source_dir: Callable[..., Path], make_terminal_config: Callable[..., TerminalConfig]
) -> None:
    """内訳を上限で切り、件数は全件を数える（正常系）。"""
    # 準備
    config = make_source_dir("alpha", unindexed=51)
    handlers = _handlers(make_terminal_config)
    # 実行
    result = check_project(CheckProjectRequest(path=str(config.parent)), handlers=handlers)
    # 検証
    assert result.sync is not None
    assert result.sync.unindexed_files == 51
    assert len(result.sync.items) == 50


def test_check_project_when_records_schema_mismatch(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """records の行のスキーマが 1 行のスキーマを持たなければ違反にする（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "project-index.yaml": FILES_ROW_CONFIG,
            "schemas/files.schema.yaml": (
                "title: file\n"
                "type: object\n"
                "required: [files]\n"
                "properties:\n"
                "  files:\n"
                "    type: array\n"
            ),
            "files.yaml": "files:\n  - path: a.md\n",
            "a.md": "# a\n",
        },
    )
    handlers = _handlers(make_terminal_config)
    # 実行
    result = check_project(CheckProjectRequest(path=str(tmp_path)), handlers=handlers)
    # 検証
    assert [violation.path for violation in result.violations] == ["documents[0].schema"]
    assert "properties.files.items" in result.violations[0].rule
    assert result.sync is None


def test_check_project_when_records_schema(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """setup が作る組み合わせは違反にしない（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "project-index.yaml": FILES_ROW_CONFIG,
            "schemas/files.schema.yaml": FILES_SCHEMA_TEMPLATE.read_text(encoding="utf-8"),
            "files.yaml": "files:\n  - path: a.md\n",
            "a.md": "# a\n",
        },
    )
    handlers = _handlers(make_terminal_config)
    # 実行
    result = check_project(CheckProjectRequest(path=str(tmp_path)), handlers=handlers)
    # 検証
    assert result.violations == []


def test_try_convert_when_converter_not_defined(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """変換を持たない種類を断る（異常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "project-index.yaml": NOTES_CONFIG,
            "schemas/rule.schema.yaml": RULE_SCHEMA,
            "docs/files.yaml": "files:\n  - path: a.md\n",
            "docs/a.md": "# A\n\n本文\n",
        },
    )
    handlers = _handlers(make_terminal_config)
    request = TryConvertRequest(path=str(tmp_path), file="docs/a.md")
    # 実行・検証
    with pytest.raises(ConverterNotDefinedError, match="converters"):
        try_convert(request, handlers=handlers)


def test_try_convert_when_script(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """配信元の変換スクリプトで変換する（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "project-index.yaml": CONVERT_CONFIG,
            "schemas/rule.schema.yaml": RULE_SCHEMA,
            "docs/rule/doc-1.yaml": "id: doc-1\n",
            "scripts/convert.py": "print('# converted')\n",
        },
    )
    handlers = _handlers(make_terminal_config)
    request = TryConvertRequest(path=str(tmp_path), file="docs/rule/doc-1.yaml")
    # 実行
    result = try_convert(request, handlers=handlers)
    # 検証
    assert result.converter == "scripts/convert.py"
    assert result.markdown.strip() == "# converted"
    assert list(handlers.converter.cache_dir.glob("*")) == []


def test_try_convert_when_outside(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """配信元の外を指す（異常系）。"""
    # 準備
    write_files(
        tmp_path / "ws",
        {"project-index.yaml": NOTES_CONFIG, "schemas/rule.schema.yaml": RULE_SCHEMA},
    )
    write_files(tmp_path, {"other.md": "# other\n"})
    handlers = _handlers(make_terminal_config)
    request = TryConvertRequest(path=str(tmp_path / "ws"), file="../other.md")
    # 実行・検証
    with pytest.raises(DocumentNotFoundError):
        try_convert(request, handlers=handlers)


def test_try_convert_when_not_matched(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """どの種類にも当たらない（異常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "project-index.yaml": NOTES_CONFIG,
            "schemas/rule.schema.yaml": RULE_SCHEMA,
            "README.txt": "text\n",
        },
    )
    handlers = _handlers(make_terminal_config)
    request = TryConvertRequest(path=str(tmp_path), file="README.txt")
    # 実行・検証
    with pytest.raises(DocumentNotFoundError):
        try_convert(request, handlers=handlers)


def test_try_convert_when_script_failed(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """変換スクリプトが失敗する（異常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "project-index.yaml": CONVERT_CONFIG,
            "schemas/rule.schema.yaml": RULE_SCHEMA,
            "docs/rule/doc-1.yaml": "id: doc-1\n",
            "scripts/convert.py": "import sys\nsys.exit(1)\n",
        },
    )
    handlers = _handlers(make_terminal_config)
    request = TryConvertRequest(path=str(tmp_path), file="docs/rule/doc-1.yaml")
    # 実行・検証
    with pytest.raises(ConvertScriptError):
        try_convert(request, handlers=handlers)


def test_try_convert_when_invalid_config(
    tmp_path: Path, make_terminal_config: Callable[..., TerminalConfig]
) -> None:
    """配信元の設定が違反する（異常系）。"""
    # 準備
    handlers = _handlers(make_terminal_config)
    request = TryConvertRequest(
        path=str(tmp_path),
        file="docs/a.md",
        config=(
            "documents:\n  - id: notes\n    paths: [docs/*.md]\n"
            "    schema: schemas/rule.schema.yaml\n"
        ),
    )
    # 実行・検証
    with pytest.raises(ValidationFailedError):
        try_convert(request, handlers=handlers)


def test_load_candidate(make_source_dir: Callable[..., Path]) -> None:
    """フォルダから設定を読む（正常系）。"""
    # 準備
    config = make_source_dir("alpha")
    # 実行
    candidate = _load_candidate(str(config.parent), config=None)
    # 検証
    assert candidate.source is not None
    assert candidate.source.id == "alpha"
    assert candidate.source.root == config.parent
    assert candidate.violations == []


def test_load_candidate_when_config_text(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """書く前の設定の相対パスを配信元のフォルダから解く（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {"schemas/rule.schema.yaml": RULE_SCHEMA, "docs/rule/doc-1.yaml": "id: doc-1\n"},
    )
    config_text = (
        "name: draft\n"
        "documents:\n"
        "  - id: rules\n"
        "    paths: [docs/rule/*.yaml]\n"
        "    schema: schemas/rule.schema.yaml\n"
    )
    # 実行
    candidate = _load_candidate(str(tmp_path), config=config_text)
    # 検証
    assert candidate.source is not None
    assert candidate.source.root == tmp_path
    assert not (tmp_path / "project-index.yaml").exists()


def test_load_candidate_when_legacy_config(make_source_dir: Callable[..., Path]) -> None:
    """移行の間の dev-docs.yaml を読む（正常系）。"""
    # 準備
    config = make_source_dir("alpha")
    legacy = config.with_name("dev-docs.yaml")
    config.rename(legacy)
    # 実行
    candidate = _load_candidate(str(legacy.parent), config=None)
    # 検証
    assert candidate.source is not None
    assert candidate.source.id == "alpha"
    # project-index.yaml を置くと、そちらを読む
    config.write_text(legacy.read_text(encoding="utf-8").replace("alpha", "beta", 1), encoding="utf-8")
    assert _load_candidate(str(legacy.parent), config=None).source.id == "beta"


def test_load_candidate_when_not_found(tmp_path: Path) -> None:
    """設定が無い（異常系）。"""
    # 実行・検証
    with pytest.raises(ConfigNotFoundError):
        _load_candidate(str(tmp_path), config=None)


def test_load_candidate_when_parse_error(tmp_path: Path) -> None:
    """YAML として読めない（異常系）。"""
    # 実行・検証
    with pytest.raises(ConfigParseError):
        _load_candidate(str(tmp_path), config="name: [")


def test_source_states(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """状態ごとに持つ値を分ける（正常系）。"""
    # 準備
    old = make_source_dir("old", version="0")
    write_files(tmp_path / "broken", {"project-index.yaml": BROKEN_CONFIG.format(name="broken")})
    off = make_source_dir("off")
    handlers = _handlers(
        make_terminal_config,
        make_entry(str(old), source_id="old"),
        make_entry(str(tmp_path / "broken" / "project-index.yaml"), source_id="broken"),
        make_entry(str(off), source_id="off", enabled=False),
    )
    # 実行
    states = _source_states(handlers)
    # 検証
    assert [state.id for state in states] == ["old", "broken", "off"]
    assert states[0].version_state == "old"
    assert states[0].sync is not None
    assert states[1].errors[0].startswith("documents[0].paths: ")
    assert states[1].version_state is None
    assert states[1].sync is None
    assert states[2].errors == []
    assert states[2].sync is None


@pytest.mark.parametrize(
    ("mine", "current", "expected"),
    [
        pytest.param("1", "1", "current", id="same"),
        pytest.param("1", "2", "old", id="older"),
        pytest.param("3", "2", "newer", id="newer"),
    ],
)
def test_version_state(mine: str, current: str, expected: str) -> None:
    """同じ・古い・新しいを分ける（正常系）。"""
    # 実行
    result = version_state(mine, current)
    # 検証
    assert result == expected


def test_version_state_when_not_integer() -> None:
    """整数でない（異常系）。"""
    # 実行・検証
    with pytest.raises(ValueError, match="invalid literal"):
        version_state("a", "1")


NAV_CONFIG = (
    "name: navs\n"
    "documents:\n"
    "  - id: rules\n"
    "    paths: [docs/rule/*.yaml]\n"
    "    schema: schemas/rule.schema.yaml\n"
    "# 画面の構成\n"
    "nav:\n"
    "  tabs:\n"
    "    - title: 設計\n"
    "      items:\n"
    "        - group: MCP\n"
    "          items:\n"
    "            - page: rules/doc-1\n"
)


@pytest.fixture
def nav_source(tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]) -> Path:
    """`nav` にタブ `設計`（group `MCP`）を持つ配信元のフォルダを作り、そのフォルダを返す。"""
    root = tmp_path / "navs"
    write_files(
        root,
        {
            "project-index.yaml": NAV_CONFIG,
            "schemas/rule.schema.yaml": RULE_SCHEMA,
            "docs/rule/doc-1.yaml": "id: doc-1\nname: 文書 1\ntags: [mcp]\n",
            "docs/rule/doc-2.yaml": "id: doc-2\nname: 文書 2\ntags: [設計]\n",
        },
    )
    return root


def test_check_project_when_alias_and_nav(
    make_alias_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """エイリアスのキーの違反と nav の警告（正常系）。"""
    # 準備
    config = make_alias_source_dir(broken=True, none_nav=True)
    handlers = _handlers(make_terminal_config)
    # 実行
    result = check_project(CheckProjectRequest(path=str(config.parent)), handlers=handlers)
    # 検証
    assert [(item.doc, item.path) for item in result.violations] == [
        ("docs/term/broken.yaml", "aliases")
    ]
    assert len(result.warnings) == 1
    assert result.warnings[0].path.startswith("nav.tabs[1].")
    assert result.warnings[0].rule.startswith("none:")
    assert result.alias_schema_version == "v0.3.0"


def test_write_nav(nav_source: Path, make_terminal_config: Callable[..., TerminalConfig]) -> None:
    """タブを足して group を直す（正常系）。"""
    from project_index.features.admin.service import write_nav
    from project_index.features.admin.types import NavOperation, WriteNavRequest

    # 準備
    handlers = _handlers(make_terminal_config)
    request = WriteNavRequest(
        path=str(nav_source),
        operations=[
            NavOperation(
                op="add",
                tab="mcp",
                value={
                    "title": "mcp",
                    "items": [
                        {"auto": {"filter": {"field": "tags", "op": "eq", "values": ["mcp"]}}}
                    ],
                },
            ),
            NavOperation(op="update", tab="設計", item="MCP", value={"title": "MCP のツール"}),
        ],
    )
    # 実行
    result = write_nav(request, handlers=handlers)
    # 検証
    text = (nav_source / "project-index.yaml").read_text(encoding="utf-8")
    written = load_yaml(text)
    assert [tab["title"] for tab in written["nav"]["tabs"]] == ["設計", "mcp"]
    assert written["nav"]["tabs"][0]["items"][0]["title"] == "MCP のツール"
    assert text.startswith(NAV_CONFIG.split("nav:\n")[0])
    assert [(count.tab, count.count) for count in result.counts] == [("mcp", 1)]
    assert result.warnings == []


def test_write_nav_when_zero_count(
    nav_source: Path, make_terminal_config: Callable[..., TerminalConfig]
) -> None:
    """0 件の条件も書いて警告する（正常系）。"""
    from project_index.features.admin.service import write_nav
    from project_index.features.admin.types import NavOperation, WriteNavRequest

    # 準備
    handlers = _handlers(make_terminal_config)
    request = WriteNavRequest(
        path=str(nav_source),
        operations=[
            NavOperation(
                op="add",
                tab="none",
                value={
                    "title": "none",
                    "items": [
                        {"auto": {"filter": {"field": "tags", "op": "eq", "values": ["none"]}}}
                    ],
                },
            )
        ],
    )
    # 実行
    result = write_nav(request, handlers=handlers)
    # 検証
    written = load_yaml((nav_source / "project-index.yaml").read_text(encoding="utf-8"))
    assert [tab["title"] for tab in written["nav"]["tabs"]] == ["設計", "none"]
    assert len(result.warnings) == 1
    assert result.warnings[0].path == "nav.tabs[1].items[0].auto.filter"
    assert result.warnings[0].rule.startswith("none:")


def test_write_nav_when_records_filter(
    make_records_nav_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """records の行の 1 行の項目の条件を書ける（正常系）。"""
    from project_index.features.admin.service import write_nav
    from project_index.features.admin.types import NavOperation, WriteNavRequest

    # 準備
    config = make_records_nav_source_dir("owner", "string", {"a": "alice"})
    handlers = _handlers(make_terminal_config)
    request = WriteNavRequest(
        path=str(config.parent),
        operations=[
            NavOperation(
                op="add",
                tab="files",
                value={
                    "title": "files",
                    "items": [
                        {
                            "auto": {
                                "document": "notes",
                                "filter": {"field": "owner", "op": "eq", "values": ["alice"]},
                            }
                        }
                    ],
                },
            )
        ],
    )
    # 実行
    result = write_nav(request, handlers=handlers)
    # 検証
    assert [(count.tab, count.count) for count in result.counts] == [("files", 1)]
    assert result.warnings == []


def test_write_nav_when_invalid_filter(
    nav_source: Path, make_terminal_config: Callable[..., TerminalConfig]
) -> None:
    """使えない条件（異常系）。"""
    from project_index.features.admin.service import write_nav
    from project_index.features.admin.types import NavOperation, WriteNavRequest
    from project_index.shared.errors import NavInvalidError

    # 準備
    handlers = _handlers(make_terminal_config)
    request = WriteNavRequest(
        path=str(nav_source),
        operations=[
            NavOperation(
                op="add",
                tab="x",
                value={
                    "title": "x",
                    "items": [{"auto": {"filter": {"field": "nmae", "op": "eq", "values": ["x"]}}}],
                },
            )
        ],
    )
    # 実行・検証
    with pytest.raises(NavInvalidError, match="画面の構成が正しくありません") as caught:
        write_nav(request, handlers=handlers)
    assert [item.path for item in caught.value.violations] == [
        "nav.tabs[1].items[0].auto.filter.field"
    ]
    assert (nav_source / "project-index.yaml").read_text(encoding="utf-8") == NAV_CONFIG


def test_write_nav_when_missing_tab(
    nav_source: Path, make_terminal_config: Callable[..., TerminalConfig]
) -> None:
    """無いタブ（異常系）。"""
    from project_index.features.admin.service import write_nav
    from project_index.features.admin.types import NavOperation, WriteNavRequest
    from project_index.shared.errors import InvalidArgumentError

    # 準備
    handlers = _handlers(make_terminal_config)
    request = WriteNavRequest(
        path=str(nav_source), operations=[NavOperation(op="remove", tab="none")]
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="引数が正しくありません") as caught:
        write_nav(request, handlers=handlers)
    assert caught.value.violations[0].path == "operations[0]"
    assert "設計" in caught.value.violations[0].fix


def test_write_nav_when_overlaid_nav(
    nav_source: Path,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """重ねた設定が nav を持つ（異常系）。"""
    from project_index.features.admin.service import write_nav
    from project_index.features.admin.types import NavOperation, WriteNavRequest
    from project_index.shared.errors import InvalidArgumentError

    # 準備
    local = nav_source / "local.yaml"
    local.write_text("nav:\n  tabs: []\n", encoding="utf-8")
    entry = make_entry([str(nav_source / "project-index.yaml"), str(local)], source_id="navs")
    handlers = _handlers(make_terminal_config, entry)
    request = WriteNavRequest(
        path=str(nav_source),
        operations=[NavOperation(op="update", tab="設計", value={"title": "設計書"})],
    )
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="引数が正しくありません"):
        write_nav(request, handlers=handlers)


def test_source_states_when_not_checked(
    monkeypatch: pytest.MonkeyPatch,
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """検査が済んでいない配信元は同期の件数を持たず、ファイルをたどらない（正常系）。"""
    # 準備
    from project_index.features.admin import service as service_module

    alpha = make_source_dir("alpha", unindexed=1)
    terminal = make_terminal_config(sources=[make_entry(str(alpha), source_id="alpha")])
    handlers = build_handlers(terminal)
    handlers.registry.reload(terminal)
    calls: list[str] = []

    def failing_check_sync(store: Any, source: Any) -> Any:
        calls.append(source.id)
        raise AssertionError("check_sync を呼んだ")

    monkeypatch.setattr(service_module, "check_sync", failing_check_sync, raising=False)
    # 実行
    states = _source_states(handlers)
    # 検証
    assert [(state.id, state.status) for state in states] == [("alpha", "serving")]
    assert states[0].sync is None
    assert calls == []


def test_source_states_without_refresh(
    monkeypatch: pytest.MonkeyPatch,
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """配信元ごとの `default_ref` の commit を確かめず、いま配信中の組を読む（正常系）。"""
    # 準備
    alpha = make_source_dir("alpha", unindexed=1)
    terminal = make_terminal_config(sources=[make_entry(str(alpha), source_id="alpha")])
    handlers = build_handlers(terminal)
    handlers.registry.reload(terminal)
    [served] = handlers.registry.served()
    calls: list[str] = []

    def failing_get(source_id: str) -> Any:
        calls.append(source_id)
        raise AssertionError("registry.get を呼んだ")

    monkeypatch.setattr(handlers.registry, "get", failing_get)
    # 実行
    states = _source_states(handlers)
    # 検証
    assert [(state.id, state.status) for state in states] == [("alpha", "serving")]
    assert states[0].config_version == served.config.version
    assert calls == []

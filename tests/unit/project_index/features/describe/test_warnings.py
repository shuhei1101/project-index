from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.access.types import SourceAccess
from project_index.features.describe.source_checks import SourceChecks
from project_index.features.describe.warnings import collect_warnings
from project_index.main import Handlers, build_handlers

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.settings.types import SourceEntry, TerminalConfig

MISSING_FILES_CONFIG = (
    "name: a\n"
    'version: "0"\n'
    "documents:\n"
    "  - id: src\n"
    "    paths: [src/files.yaml]\n"
    "    schema: schemas/files.schema.yaml\n"
    "    records: files\n"
    "    body_file: path\n"
)
BROKEN_CONFIG = "name: b\ndocuments:\n  - id: rules\n    schema: schemas/rule.schema.yaml\n"


def _loaded_handlers(terminal: TerminalConfig) -> Handlers:
    """部品を本物で配線し、配信元を読んだ配線済みの関数を作る。"""
    handlers = build_handlers(terminal)
    handlers.reload_sources(terminal)
    return handlers


def _access(source_id: str, access: str = "write", description: str = "") -> SourceAccess:
    """使える配信元の 1 行を作る。"""
    return SourceAccess(
        source_id=source_id,
        access=access,  # type: ignore[arg-type]
        current=False,
        description=description,
    )


def test_collect_warnings(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """同期のずれ・古い設定・配信していない配信元を並べる（正常系）。"""
    # 準備
    write_files(
        tmp_path / "a",
        {
            "project-index.yaml": MISSING_FILES_CONFIG,
            "schemas/files.schema.yaml": "title: file\ntype: object\n",
            "src/files.yaml": (
                "files:\n"
                "  - path: x.py\n"
                "  - path: y.py\n"
                "  - path: z.py\n"
                "    related:\n"
                "      - to: src/none.py\n"
            ),
            "src/z.py": "z = 1\n",
        },
    )
    write_files(tmp_path / "b", {"project-index.yaml": BROKEN_CONFIG})
    handlers = _loaded_handlers(
        make_terminal_config(
            sources=[
                make_entry(str(tmp_path / "a" / "project-index.yaml"), source_id="a"),
                make_entry(str(tmp_path / "b" / "project-index.yaml"), source_id="b"),
            ]
        )
    )
    # 実行
    result = collect_warnings(
        [_access("a")],
        registry=handlers.registry,
        checks=handlers.checks,
        terminal=handlers.terminal,
    )
    # 検証
    assert len(result) == 4
    assert result[0].startswith("a: ")
    assert "2 件" in result[0]
    assert "check_project" in result[0]
    assert result[1].startswith("a: ")
    assert "1 件" in result[1]
    assert "check_project" in result[1]
    assert result[2].startswith("a: 設定のバージョンが古い")
    assert result[3].startswith("b: 配信していません")


def test_collect_warnings_when_unavailable_source(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """使えない配信元の同期のずれは載せない（正常系）。"""
    # 準備
    handlers = _loaded_handlers(
        make_terminal_config(
            sources=[make_entry(str(make_source_dir("a", unindexed=1)), source_id="a")]
        )
    )
    # 実行
    result = collect_warnings(
        [], registry=handlers.registry, checks=handlers.checks, terminal=handlers.terminal
    )
    # 検証
    assert result == []


def test_collect_warnings_when_alias_and_nav(
    make_alias_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """エイリアスのキーの違反と nav の警告（正常系）。"""
    # 準備
    config = make_alias_source_dir("a", broken=True, none_nav=True)
    handlers = _loaded_handlers(
        make_terminal_config(sources=[make_entry(str(config), source_id="a")])
    )
    # 実行
    result = collect_warnings(
        [_access("a")],
        registry=handlers.registry,
        checks=handlers.checks,
        terminal=handlers.terminal,
    )
    # 検証
    assert result[0] == "a: エイリアスのキーの違反が 1 件あります（check_project で確認できます）"
    assert result[1].startswith("a: nav.tabs[1].items[0].auto.filter: none:")
    assert len(result) == 2


def test_collect_warnings_when_unchecked(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """まだ検査していない配信元は、同期のずれを載せない（正常系）。"""
    # 準備
    handlers = _loaded_handlers(
        make_terminal_config(
            sources=[make_entry(str(make_source_dir("a", unindexed=1)), source_id="a")]
        )
    )
    # 実行
    result = collect_warnings(
        [_access("a")],
        registry=handlers.registry,
        checks=SourceChecks(),
        terminal=handlers.terminal,
    )
    # 検証
    assert result == []


def test_collect_warnings_when_no_source_available(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """使える配信元が無くても、端末の設定の古さと配信していない配信元を載せる（正常系）。"""
    # 準備
    write_files(tmp_path / "b", {"project-index.yaml": BROKEN_CONFIG})
    handlers = _loaded_handlers(
        make_terminal_config(
            version="0",
            sources=[make_entry(str(tmp_path / "b" / "project-index.yaml"), source_id="b")],
        )
    )
    # 実行
    result = collect_warnings(
        [], registry=handlers.registry, checks=handlers.checks, terminal=handlers.terminal
    )
    # 検証
    assert len(result) == 2
    assert result[0].startswith("端末の設定: 設定のバージョンが古い")
    assert result[1].startswith("b: 配信していません")

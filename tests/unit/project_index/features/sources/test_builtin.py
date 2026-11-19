from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from project_index.features.sources.builtin import load_builtin_source

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.settings.types import SourceEntry, TerminalConfig

# リポジトリの雛形の管理用の YAML のスキーマ（組み込みの配信元が差し替える先）
FILES_SCHEMA = (Path(__file__).resolve().parents[5] / "templates" / "files.schema.yaml").read_text(
    encoding="utf-8"
)

CLONE_CONFIG = (
    'version: "3"\n'
    "name: project-index\n"
    "documents:\n"
    "  - id: files_guide\n"
    "    paths: [docs/guide/files.yml]\n"
    "    schema:\n"
    "      source: knowledge\n"
    "      path: schemas/knowledge-files.schema.yaml\n"
    "      ref: design-schemas/v9.2.0\n"
    "    records: files\n"
    "    body_file: path\n"
    "  - id: src\n"
    "    paths: [src/files.yaml]\n"
    "    schema:\n"
    "      source: knowledge\n"
    "      path: schemas/knowledge-files.schema.yaml\n"
    "      ref: design-schemas/v9.2.0\n"
    "    records: files\n"
    "    body_file: path\n"
)

SRC_ONLY_CONFIG = (
    'version: "3"\n'
    "name: project-index\n"
    "documents:\n"
    "  - id: src\n"
    "    paths: [src/files.yaml]\n"
    "    schema: templates/files.schema.yaml\n"
    "    records: files\n"
    "    body_file: path\n"
)

GUIDE_FILES = "files:\n- path: 配信元を登録する.md\n  visibility: public\n"


def test_load_builtin_source(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """ガイドの行だけの読み取りだけの配信元を作る（正常系）。"""
    # 準備
    clone = tmp_path / "clone"
    write_files(
        clone,
        {
            "project-index.yaml": CLONE_CONFIG,
            "templates/files.schema.yaml": FILES_SCHEMA,
            "docs/guide/files.yml": GUIDE_FILES,
            "docs/guide/配信元を登録する.md": "# 配信元を登録する\n",
            "src/files.yaml": "files: []\n",
        },
    )
    terminal = make_terminal_config(clone=clone, sources=[])
    # 実行
    served, reason = load_builtin_source(terminal)
    # 検証
    assert reason is None
    assert served is not None
    assert served.id == "project-index"
    assert [row.id for row in served.config.documents] == ["files_guide"]
    assert served.config.documents[0].schema_path == "templates/files.schema.yaml"
    assert served.scope_read == []
    assert served.scope_write == []
    assert served.outside_read is True
    assert served.storage == "disk"
    assert served.builtin is True


def test_load_builtin_source_when_registered(
    tmp_path: Path,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """project-index の行があれば加えない（正常系）。"""
    # 準備
    clone = tmp_path / "clone"
    entry = make_entry(
        str(tmp_path / "other" / "project-index.yaml"), source_id="project-index", enabled=False
    )
    terminal = make_terminal_config(clone=clone, sources=[entry])
    # 実行
    result = load_builtin_source(terminal)
    # 検証
    assert result == (None, None)
    assert not clone.exists()


def test_load_builtin_source_when_config_missing(
    tmp_path: Path,
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """クローンに設定が無い（異常系）。"""
    # 準備
    clone = tmp_path / "clone"
    clone.mkdir()
    terminal = make_terminal_config(clone=clone, sources=[])
    # 実行
    served, reason = load_builtin_source(terminal)
    # 検証
    assert served is None
    assert reason is not None
    assert str(clone / "project-index.yaml") in reason


def test_load_builtin_source_when_row_missing(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_terminal_config: Callable[..., TerminalConfig],
) -> None:
    """ガイドの行が無い（異常系）。"""
    # 準備
    clone = tmp_path / "clone"
    write_files(
        clone,
        {
            "project-index.yaml": SRC_ONLY_CONFIG,
            "templates/files.schema.yaml": FILES_SCHEMA,
            "src/files.yaml": "files: []\n",
        },
    )
    terminal = make_terminal_config(clone=clone, sources=[])
    # 実行
    served, reason = load_builtin_source(terminal)
    # 検証
    assert served is None
    assert reason is not None
    assert "files_guide" in reason

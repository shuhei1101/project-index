"""クローンのガイドを組み込みの配信元にする。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from project_index.features.sources.service import assemble_values, entry_source_id
from project_index.features.sources.types import SOURCE_CONFIG_VERSION
from project_index.shared.narrowing import is_dict
from project_index.shared.yaml_io import YamlLoadError, load_yaml

if TYPE_CHECKING:
    from pathlib import Path

    from project_index.features.settings.types import TerminalConfig
    from project_index.features.sources.types import ServedSource

__all__ = ["BUILTIN_ROW_ID", "BUILTIN_SCHEMA_PATH", "BUILTIN_SOURCE_ID", "load_builtin_source"]

# 組み込みの配信元の ID と、端末の設定に同じ配信元の行があるかの照合に使用する ID
BUILTIN_SOURCE_ID = "project-index"
# クローンの `project-index.yaml` から取り出す `documents[]` の行の ID
BUILTIN_ROW_ID = "files_guide"
# 取り出した行の `schema` を差し替える、クローンの直下からのスキーマのパス
BUILTIN_SCHEMA_PATH = "templates/files.schema.yaml"


def load_builtin_source(terminal: TerminalConfig) -> tuple[ServedSource | None, str | None]:
    """端末の設定に project-index の行が無いとき、クローンのガイドの行だけを読み取りだけの配信元にする。"""
    # 端末の設定に同じ ID の行がある（無効な行を含む）: 組み込みの配信元を加えない
    if any(entry_source_id(entry) == BUILTIN_SOURCE_ID for entry in terminal.sources):
        return None, None
    config_file = terminal.clone / "project-index.yaml"
    row = _guide_row(config_file)
    # 行を取り出せなかった: 理由を返して加えない
    if isinstance(row, str):
        return None, row
    values: dict[str, Any] = {
        "version": SOURCE_CONFIG_VERSION,
        "name": BUILTIN_SOURCE_ID,
        "documents": [{**row, "schema": BUILTIN_SCHEMA_PATH}],
    }
    served, _config, violations = assemble_values(
        values,
        root=terminal.clone,
        source_id=BUILTIN_SOURCE_ID,
        scope_read=[],
        scope_write=[],
        outside_read=True,
        storage="disk",
        builtin=True,
    )
    if violations:
        return None, f"{config_file}: {violations[0].path}: {violations[0].rule}"
    return served, None


def _guide_row(config_file: Path) -> dict[str, Any] | str:
    """クローンの設定からガイドの行を取り出す。取り出せなければ理由の文字列を返す。"""
    if not config_file.is_file():
        return f"{config_file} がありません"
    try:
        value = load_yaml(config_file.read_text(encoding="utf-8"), file=str(config_file))
    except YamlLoadError as error:
        return f"{config_file} を YAML として読み込めません（{error}）"
    documents = value.get("documents") if is_dict(value) else None
    rows = cast("list[object]", documents) if isinstance(documents, list) else []
    for row in rows:
        # ガイドの行: そのまま返す（キーの検査は組み立ての検証が行う）
        if is_dict(row) and row.get("id") == BUILTIN_ROW_ID:
            return cast("dict[str, Any]", row)
    return f"{config_file} に documents の行 {BUILTIN_ROW_ID} がありません"

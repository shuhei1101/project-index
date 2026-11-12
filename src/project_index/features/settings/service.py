"""端末の設定の API からの端末の設定の保存と 1 行の追加。"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from project_index.features.settings.query import load_terminal_config, validate_terminal_config
from project_index.features.settings.types import (
    SourceAddResult,
    SourceEntry,
    TerminalConfig,
    TerminalConfigInvalidError,
)
from project_index.shared.files import replace_file
from project_index.shared.yaml_io import dump_roundtrip, load_roundtrip

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from project_index.features.sources.types import SourceStatus

logger = logging.getLogger(__name__)


def _to_yaml_row(entry: SourceEntry) -> dict[str, Any]:
    """既定値と同じキーを書かない `sources[]` の 1 行にする。"""
    row: dict[str, Any] = {}
    if entry.id is not None:
        row["id"] = entry.id
    row["config"] = list(entry.config)
    if not entry.enabled:
        row["enabled"] = False
    if not entry.outside_read:
        row["outside_read"] = False
    scope: dict[str, Any] = {}
    if entry.scope.read:
        scope["read"] = list(entry.scope.read)
    if entry.scope.write is not None:
        scope["write"] = list(entry.scope.write)
    if scope:
        row["scope"] = scope
    return row


def _validate_or_raise(document: object, path: Path) -> None:
    """書き換えた端末の設定を検証し、違反があれば `TerminalConfigInvalidError` を送る。"""
    plain = json.loads(json.dumps(document, default=str))
    violations = validate_terminal_config(plain)
    if violations:
        raise TerminalConfigInvalidError(
            file=path,
            message=f"{path}: 端末の設定に違反が {len(violations)} 件あります",
            violations=violations,
        )


def save_sources(
    sources: Sequence[SourceEntry],
    *,
    path: Path,
    reload: Callable[[TerminalConfig], list[SourceStatus]],
    lock: threading.Lock,
) -> list[SourceStatus]:
    """`settings.yaml` の `sources` だけを書き換え、検証に通ったら書いて配信元を読み直す。"""
    with lock:
        # sources だけを送られた行に置き換える（他のキーとコメントは保つ）
        document = load_roundtrip(path.read_text(encoding="utf-8"), file=str(path))
        document["sources"] = [_to_yaml_row(entry) for entry in sources]
        # 置き換えた後を検証し、違反があれば書かない
        _validate_or_raise(document, path)
        replace_file(path, dump_roundtrip(document))
        logger.info("端末の設定の sources を保存した（%s・%s 行）", path, len(sources))
        return reload(load_terminal_config(path))


def add_source(
    source: SourceEntry,
    *,
    path: Path,
    reload: Callable[[TerminalConfig], list[SourceStatus]],
    lock: threading.Lock,
) -> SourceAddResult:
    """同じ id の行が無ければ `sources` の末尾に 1 行追加して読み直し、あれば内容が同じかを返す。"""
    with lock:
        document = load_roundtrip(path.read_text(encoding="utf-8"), file=str(path))
        current_rows = cast("Mapping[str, list[object] | None]", document).get("sources")
        rows: list[object] = list(current_rows or [])
        row = _to_yaml_row(source)
        # 同じ id の行がある: 既定値を書かない形にそろえて比べ、ファイルは書かない
        if source.id is not None:
            for existing in rows:
                if (
                    isinstance(existing, Mapping)
                    and cast("Mapping[str, object]", existing).get("id") == source.id
                ):
                    current = SourceEntry.model_validate(json.loads(json.dumps(existing)))
                    return SourceAddResult(result="exists", same=_to_yaml_row(current) == row)
        document["sources"] = [*rows, row]
        # 加えた後を検証し、違反があれば書かない
        _validate_or_raise(document, path)
        replace_file(path, dump_roundtrip(document))
        logger.info("端末の設定の sources に 1 行追加した（%s・%s）", path, source.id)
        return SourceAddResult(result="added", statuses=reload(load_terminal_config(path)))

"""端末の設定の API からの端末の設定の保存と、1 行ずつの追加・変更・削除。"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from project_index.features.settings.query import (
    load_terminal_config,
    read_settings_file,
    validate_terminal_config,
)
from project_index.features.settings.types import (
    SettingsVersionMismatchError,
    SourceAddResult,
    SourceEntry,
    SourcePatch,
    SourceRowNotFoundError,
    SourceScope,
    SourceWriteResult,
    TerminalConfig,
    TerminalConfigInvalidError,
)
from project_index.features.sources.service import entry_source_id
from project_index.shared.errors import Violation
from project_index.shared.files import replace_file
from project_index.shared.yaml_io import dump_roundtrip, load_roundtrip

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from ruamel.yaml.comments import CommentedMap

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


def _current_entries(document: object) -> dict[str, SourceEntry]:
    """ファイルの `sources` の行を、配信元の ID ごとに引ける形にする（読めない行・ID が求まらない行は除く）。"""
    rows = cast("Mapping[str, list[object] | None]", document).get("sources") or []
    current: dict[str, SourceEntry] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        # スキーマに通らない行は、送られた行で置き換えれば直るため探す対象から除く
        try:
            entry = SourceEntry.model_validate(json.loads(json.dumps(row)))
        except ValidationError:
            continue
        source_id = entry_source_id(entry)
        if source_id is not None:
            current.setdefault(source_id, entry)
    return current


def _fill_unsent(entry: SourceEntry, current: Mapping[str, SourceEntry]) -> SourceEntry:
    """行に含めなかったキーを、ファイルの同じ配信元の行の値で埋める。"""
    source_id = entry_source_id(entry)
    found = current.get(source_id) if source_id is not None else None
    if found is None:
        return entry
    sent = entry.model_fields_set
    updates: dict[str, Any] = {
        key: getattr(found, key) for key in ("enabled", "outside_read") if key not in sent
    }
    # scope は read・write を別々に、送られたかで決める
    scope_sent = entry.scope.model_fields_set if "scope" in sent else set[str]()
    updates["scope"] = SourceScope(
        read=entry.scope.read if "read" in scope_sent else found.scope.read,
        write=entry.scope.write if "write" in scope_sent else found.scope.write,
    )
    return entry.model_copy(update=updates)


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


def _check_version(current: str, expected: str | None) -> None:
    """要求の内容のバージョンを今の内容のバージョンと照合し、違えば断る（`None` は照合しない）。"""
    if expected is not None and expected != current:
        raise SettingsVersionMismatchError(
            message=f"端末の設定が取得した後に書き換えられています（今の内容のバージョン: {current}）",
            next_steps=["端末の設定の配信元を取得し直してから、もう一度書き換えてください"],
            current=current,
        )


def _find_row(rows: Sequence[object], source_id: str) -> tuple[int, SourceEntry]:
    """配信元の ID が `source_id` の最初の行の位置と行を返す（読めない行は探す対象から除く）。"""
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        try:
            entry = SourceEntry.model_validate(json.loads(json.dumps(row)))
        except ValidationError:
            continue
        if entry_source_id(entry) == source_id:
            return index, entry
    raise SourceRowNotFoundError(
        message=f"端末の設定に {source_id} の行がありません",
        next_steps=["端末の設定の配信元を取得し、行の ID を確かめてください"],
        source_id=source_id,
    )


def _apply_patch(entry: SourceEntry, patch: SourcePatch) -> SourceEntry:
    """行に、変更で送ったキーだけを重ねる。"""
    sent = patch.model_fields_set
    updates: dict[str, Any] = {
        key: getattr(patch, key) for key in ("config", "enabled", "outside_read") if key in sent
    }
    # scope は read・write を別々に、送られたかで決める
    if "scope" in sent and patch.scope is not None:
        scope_sent = patch.scope.model_fields_set
        updates["scope"] = SourceScope(
            read=patch.scope.read if "read" in scope_sent else entry.scope.read,
            write=patch.scope.write if "write" in scope_sent else entry.scope.write,
        )
    return entry.model_copy(update=updates)


def _write_and_reload(
    document: CommentedMap,
    path: Path,
    reload: Callable[[TerminalConfig], list[SourceStatus]],
) -> SourceWriteResult:
    """書き換えた端末の設定を書き、読み直して配信元の状態と書いた後の内容のバージョンを返す。"""
    replace_file(path, dump_roundtrip(document))
    text, version = read_settings_file(path)
    statuses = reload(load_terminal_config(path, text=text))
    return SourceWriteResult(statuses=statuses, version=version)


def save_sources(
    sources: Sequence[SourceEntry],
    *,
    expected_version: str | None = None,
    path: Path,
    reload: Callable[[TerminalConfig], list[SourceStatus]],
    lock: threading.Lock,
) -> SourceWriteResult:
    """`settings.yaml` の `sources` だけを書き換え、検証に通ったら書いて配信元を読み直す。"""
    with lock:
        # 取得した後に書き換えられていないかを照合する
        text, current = read_settings_file(path)
        _check_version(current, expected_version)
        # sources だけを送られた行に置き換える（他のキーとコメントは保つ）
        document = load_roundtrip(text, file=str(path))
        # 送られなかったキーは、ファイルの同じ配信元の行の今の値で埋める
        current = _current_entries(document)
        filled = [_fill_unsent(entry, current) for entry in sources]
        document["sources"] = [_to_yaml_row(entry) for entry in filled]
        # 置き換えた後を検証し、違反があれば書かない
        _validate_or_raise(document, path)
        result = _write_and_reload(document, path, reload)
        logger.info("端末の設定の sources を保存した（%s・%s 行）", path, len(sources))
        return result


def add_source(
    source: SourceEntry,
    *,
    expected_version: str | None = None,
    path: Path,
    reload: Callable[[TerminalConfig], list[SourceStatus]],
    lock: threading.Lock,
) -> SourceAddResult:
    """同じ id の行が無ければ `sources` の末尾に 1 行追加して読み直し、あれば内容が同じかを返す。"""
    with lock:
        # 取得した後に書き換えられていないかを、同じ id の行の確認より前に照合する
        text, current_version = read_settings_file(path)
        _check_version(current_version, expected_version)
        document = load_roundtrip(text, file=str(path))
        current_rows = cast("Mapping[str, list[object] | None]", document).get("sources")
        rows: list[object] = list(current_rows or [])
        row = _to_yaml_row(source)
        # 同じ実効の id（`id`、無ければ設定の `name`）の行がある: 既定値を書かない形にそろえて比べ、ファイルは書かない
        source_id = entry_source_id(source)
        if source_id is not None:
            for existing in rows:
                if not isinstance(existing, Mapping):
                    continue
                current = SourceEntry.model_validate(json.loads(json.dumps(existing)))
                if entry_source_id(current) == source_id:
                    return SourceAddResult(
                        result="exists", same=_to_yaml_row(current) == row, version=current_version
                    )
        document["sources"] = [*rows, row]
        # 加えた後を検証し、違反があれば書かない
        _validate_or_raise(document, path)
        written = _write_and_reload(document, path, reload)
        logger.info("端末の設定の sources に 1 行追加した（%s・%s）", path, source.id)
        return SourceAddResult(result="added", statuses=written.statuses, version=written.version)


def patch_source(
    source_id: str,
    patch: SourcePatch,
    *,
    expected_version: str,
    path: Path,
    reload: Callable[[TerminalConfig], list[SourceStatus]],
    lock: threading.Lock,
) -> SourceWriteResult:
    """指した 1 行に送ったキーだけを重ねて `settings.yaml` を書き換え、変わった行の配信元を読み直す。"""
    with lock:
        # 取得した後に書き換えられていないかを、行の検索より前に照合する
        text, current = read_settings_file(path)
        _check_version(current, expected_version)
        document = load_roundtrip(text, file=str(path))
        rows: list[object] = list(
            cast("Mapping[str, list[object] | None]", document).get("sources") or []
        )
        index, entry = _find_row(rows, source_id)
        patched = _apply_patch(entry, patch)
        # id を省いた行の配信元の ID が変わる: 読み直す配信元が 1 つに決まらないため断る
        if entry.id is None:
            new_id = entry_source_id(patched)
            if new_id != source_id:
                raise TerminalConfigInvalidError(
                    file=path,
                    message=f"source.config: 配信元の ID が {source_id} から {new_id} に変わります",
                    violations=[
                        Violation(
                            path="source.config",
                            rule=f"配信元の ID が {source_id} から {new_id} に変わります",
                            fix="1 行の削除と追加で差し替えてください",
                        )
                    ],
                )
        rows[index] = _to_yaml_row(patched)
        document["sources"] = rows
        # 置き換えた後を検証し、違反があれば書かない
        _validate_or_raise(document, path)
        result = _write_and_reload(document, path, reload)
        logger.info("端末の設定の sources の 1 行を変更した（%s・%s）", path, source_id)
        return result


def delete_source(
    source_id: str,
    *,
    expected_version: str,
    path: Path,
    reload: Callable[[TerminalConfig], list[SourceStatus]],
    lock: threading.Lock,
) -> SourceWriteResult:
    """指した 1 行だけを `settings.yaml` の `sources` から削除し、その配信元を配信から除外する。"""
    with lock:
        # 取得した後に書き換えられていないかを、行の検索より前に照合する
        text, current = read_settings_file(path)
        _check_version(current, expected_version)
        document = load_roundtrip(text, file=str(path))
        rows: list[object] = list(
            cast("Mapping[str, list[object] | None]", document).get("sources") or []
        )
        index, _ = _find_row(rows, source_id)
        del rows[index]
        document["sources"] = rows
        # 削除した後を検証し、違反があれば書かない
        _validate_or_raise(document, path)
        result = _write_and_reload(document, path, reload)
        logger.info("端末の設定の sources から 1 行削除した（%s・%s）", path, source_id)
        return result

"""管理の MCP の `status`・`reload`・`check_project`・`try_convert`・`write_nav` の中身。"""
# pyright: reportUnknownArgumentType=warning, reportUnknownMemberType=warning, reportUnknownVariableType=warning

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
from collections.abc import Mapping, MutableMapping
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ruamel.yaml.comments import CommentedMap

from project_index.features.access.types import Target
from project_index.features.admin.types import (
    SYNC_ITEMS_LIMIT,
    CandidateSource,
    CheckProjectRequest,
    CheckProjectResult,
    CheckSync,
    NavOperation,
    NotServedItem,
    ReloadResult,
    ScriptErrorItem,
    ServerStatus,
    SourceState,
    SyncCounts,
    SyncItem,
    TerminalState,
    TryConvertRequest,
    TryConvertResult,
    VersionState,
    WriteNavRequest,
    WriteNavResult,
)
from project_index.features.convert.service import ConvertService
from project_index.features.documents.aliases import alias_schema_version
from project_index.features.documents.loader import collect_files
from project_index.features.documents.schema import records_item_schema, startup_schema
from project_index.features.documents.store import check_sync
from project_index.features.read.nav import (
    check_nav_filters,
    nav_auto_counts,
    nav_warnings,
    zero_count_warnings,
)
from project_index.features.search.fields import known_fields
from project_index.features.settings.query import (
    SETTINGS_VERSION,
    listen_port,
    load_terminal_config,
)
from project_index.features.sources.schema_ref import SchemaRefLookup, terminal_lookup
from project_index.features.sources.service import assemble_source
from project_index.features.sources.types import SOURCE_CONFIG_VERSION, ServedSource
from project_index.shared.errors import (
    ConfigNotFoundError,
    ConfigParseError,
    ConverterNotDefinedError,
    ConvertScriptError,
    DocumentNotFoundError,
    InvalidArgumentError,
    NavInvalidError,
    ValidationFailedError,
    Violation,
)
from project_index.shared.files import replace_file
from project_index.shared.paths import normalize_path
from project_index.shared.version import RUNNING_VERSION
from project_index.shared.yaml_io import YamlLoadError, dump_roundtrip, load_roundtrip, load_yaml

if TYPE_CHECKING:
    from project_index.main import Handlers

logger = logging.getLogger(__name__)

CONFIG_FILE = "project-index.yaml"
# 移行の間だけ、`project-index.yaml` が無いフォルダで読む名前
LEGACY_CONFIG_FILE = "dev-docs.yaml"
DOCUMENT_SEPARATOR = "\n\n---\n\n"


def version_state(mine: str, current: str) -> VersionState:
    """設定のバージョンを project-index が読めるバージョンと比べる。"""
    left, right = int(mine), int(current)
    if left == right:
        return "current"
    return "old" if left < right else "newer"


def _source_states(handlers: Handlers) -> list[SourceState]:
    """登録簿の状態を配信元の状態の行にする。"""
    states: list[SourceState] = []
    # 配信元ごとの `default_ref` の commit を確かめず、いま配信中の組を読む
    served = {source.id: source for source in handlers.registry.served()}
    for status in handlers.registry.statuses():
        # 配信中だけ、設定のバージョンの新旧と索引の同期の件数を持つ
        if status.status == "serving" and status.id in served:
            source = served[status.id]
            config_version = source.config.version
            # 裏で実行した検査の最後の結果を読み、配信元のファイルはたどらない
            check = handlers.checks.get(status.id)
            states.append(
                SourceState(
                    id=status.id,
                    status="serving",
                    errors=[],
                    config_version=config_version,
                    version_state=version_state(config_version, SOURCE_CONFIG_VERSION),
                    sync=None if check is None else SyncCounts.of(check.report),
                )
            )
            continue
        errors = [f"{item.path}: {item.rule}" for item in status.errors]
        states.append(
            SourceState(
                id=status.id,
                status=status.status,
                errors=errors,
                config_version=None,
                version_state=None,
                sync=None,
            )
        )
    return states


def get_status(handlers: Handlers, *, env: Mapping[str, str]) -> ServerStatus:
    """待ち受けのアドレス・バージョン・配信元ごとの状態を返す。"""
    port = listen_port(handlers.terminal, env)
    loading = handlers.registry.loading
    return ServerStatus(
        address=f"http://{handlers.terminal.bind}:{port}/",
        version=RUNNING_VERSION,
        pid=os.getpid(),
        terminal=TerminalState(
            file=str(handlers.terminal.file),
            version_state=version_state(handlers.terminal.version, SETTINGS_VERSION),
        ),
        sources=[] if loading else _source_states(handlers),
        loading=loading,
    )


def reload_config(handlers: Handlers) -> ReloadResult:
    """端末の設定と配信元の設定を読み直し、前後の差を返す。"""
    # 端末の設定の保存と同じロックの中で、一度に 1 つだけ読み直す
    with handlers.settings_lock:
        before = _serving_ids(handlers)
        terminal = load_terminal_config(handlers.terminal.file)
        statuses = handlers.reload_sources(terminal)
        after = [status.id for status in statuses if status.status == "serving"]
        result = ReloadResult(
            added=[source_id for source_id in after if source_id not in before],
            removed=[source_id for source_id in before if source_id not in after],
            not_served=[
                NotServedItem(
                    id=status.id, errors=[f"{item.path}: {item.rule}" for item in status.errors]
                )
                for status in statuses
                if status.status == "not_served"
            ],
            sources=_source_states(handlers),
        )
    logger.info(
        "設定を読み直した（追加 %s・削除 %s・配信していない %s）",
        len(result.added),
        len(result.removed),
        len(result.not_served),
    )
    return result


def _serving_ids(handlers: Handlers) -> list[str]:
    """配信中の配信元の ID を `sources[]` の順に返す。"""
    return [status.id for status in handlers.registry.statuses() if status.status == "serving"]


def _config_file(root: Path) -> Path:
    """配信元のフォルダの設定のファイルを、`project-index.yaml`・`dev-docs.yaml` の順に探す。"""
    file = root / CONFIG_FILE
    legacy = root / LEGACY_CONFIG_FILE
    # `project-index.yaml` が無く `dev-docs.yaml` がある: 移行前の名前を読む
    if not file.is_file() and legacy.is_file():
        return legacy
    return file


def _load_candidate(
    path: str, *, config: str | None, lookup: SchemaRefLookup | None = None
) -> CandidateSource:
    """パスか書く前の設定の文字列から、端末の設定によらず配信元を組み立てる。"""
    target = normalize_path(path)
    # `.yaml` で終わるパスは設定のファイル、それ以外は配信元のフォルダ
    root, config_file = (
        (target.parent, target) if target.suffix == ".yaml" else (target, _config_file(target))
    )
    if config is not None:
        text = config
    elif not config_file.is_file():
        raise ConfigNotFoundError(
            message=f"{config_file}: project-index.yaml がありません",
            path=str(config_file),
            next_steps=["/project-index:setup で配信元を追加してください"],
        )
    else:
        text = config_file.read_text(encoding="utf-8")
    try:
        value = load_yaml(text, file=str(config_file))
    except YamlLoadError as error:
        raise ConfigParseError(message=str(error), line=error.line, column=error.column) from error
    config_version = (
        str(value["version"]) if isinstance(value, dict) and "version" in value else None
    )
    # 書く前の設定は、使い捨てのフォルダに書いて読む（相対パスは配信元のフォルダから解く）
    with tempfile.TemporaryDirectory() as directory:
        file = config_file
        if config is not None:
            file = Path(directory) / CONFIG_FILE
            file.write_text(text, encoding="utf-8")
        served, loaded, violations = assemble_source(
            [file],
            source_id=None,
            scope_read=[],
            scope_write=None,
            root_override=root,
            lookup=lookup,
        )
    if loaded is None:
        return CandidateSource(
            root=root,
            config_version=config_version,
            violations=violations,
            script_violations=[],
            source=None,
        )
    # スクリプトの確かめの失敗は、スクリプトのコマンドを違反の場所にして持つ
    script_violations = [
        Violation(path=_command(loaded, violation.path), rule=violation.rule)
        for violation in violations
    ]
    return CandidateSource(
        root=root,
        config_version=config_version,
        violations=[],
        script_violations=script_violations,
        source=served,
    )


def _command(config: object, key_path: str) -> str:
    """`converters[0]` のような場所から、スクリプトのコマンドを空白でつないだ文字列にする。"""
    table, _, rest = key_path.partition("[")
    rows = getattr(config, table, [])
    return " ".join(rows[int(rest.rstrip("]"))].run)


def _registered_id(handlers: Handlers, root: Path) -> str | None:
    """端末の設定に、`config` の先頭のファイルのフォルダが同じ行があれば、その ID を返す。"""
    statuses = handlers.registry.statuses()
    for index, entry in enumerate(handlers.terminal.sources):
        if normalize_path(entry.config[0]).parent == root:
            if entry.id:
                return entry.id
            return statuses[index].id if index < len(statuses) else None
    return None


def check_project(request: CheckProjectRequest, *, handlers: Handlers) -> CheckProjectResult:
    """端末の設定に無い配信元も含め、設定・スクリプト・索引の同期を検査する。"""
    candidate = _load_candidate(
        request.path, config=request.config, lookup=terminal_lookup(handlers.terminal)
    )
    registered_id = _registered_id(handlers, candidate.root)
    state = (
        version_state(candidate.config_version, SOURCE_CONFIG_VERSION)
        if candidate.config_version is not None and candidate.config_version.isdecimal()
        else None
    )
    result = CheckProjectResult(
        path=str(candidate.root),
        registered_id=registered_id,
        config_version=candidate.config_version,
        version_state=state,
        violations=candidate.violations,
        missing_paths=[],
        script_errors=[
            ScriptErrorItem(script=item.path, reason=item.rule)
            for item in candidate.script_violations
        ],
        sync=None,
        alias_schema_version=alias_schema_version(),
    )
    # 配信元を組み立てられなかった（違反かスクリプトの失敗）ときは、ここまで
    source = candidate.source
    if source is None:
        return result
    # records の行のスキーマから 1 行のスキーマを取り出せない組み合わせは違反にする
    records_violations = _records_schema_violations(source)
    if records_violations:
        return replace(result, violations=records_violations)
    missing_paths = [
        pattern
        for table in source.config.documents
        for pattern in table.paths
        if not collect_files(source.root, replace(table, paths=[pattern]))
    ]
    report = check_sync(handlers.store, source)
    entries = (
        ("missing_refs", report.missing_refs),
        ("unindexed_files", report.unindexed_files),
        ("missing_body_files", report.missing_body_files),
        ("unresolved_related", report.unresolved_related),
    )
    items = [SyncItem(kind=kind, path=path) for kind, paths in entries for path in paths]  # type: ignore[arg-type]
    counts = SyncCounts.of(report)
    return CheckProjectResult(
        path=result.path,
        registered_id=registered_id,
        config_version=candidate.config_version,
        version_state=state,
        violations=list(report.alias_violations),
        missing_paths=missing_paths,
        script_errors=[],
        sync=CheckSync(
            missing_refs=counts.missing_refs,
            unindexed_files=counts.unindexed_files,
            missing_body_files=counts.missing_body_files,
            unresolved_related=counts.unresolved_related,
            items=items[:SYNC_ITEMS_LIMIT],
        ),
        warnings=nav_warnings(handlers.store, source),
        alias_schema_version=alias_schema_version(),
    )


def _records_schema_violations(source: ServedSource) -> list[Violation]:
    """`records` を持つ有効な行のうち、スキーマに `properties.{records}.items` が無い行の違反を返す。"""
    violations: list[Violation] = []
    for index, table in enumerate(source.config.documents):
        if not table.enabled or table.records is None:
            continue
        schema = startup_schema(source, table)
        if records_item_schema(schema, table.records) is None:
            violations.append(
                Violation(
                    path=f"documents[{index}].schema",
                    rule=(
                        f"records: {table.records} の行のスキーマに "
                        f"properties.{table.records}.items がありません"
                    ),
                )
            )
    return violations


def try_convert(request: TryConvertRequest, *, handlers: Handlers) -> TryConvertResult:
    """指した配信元のファイルを、配信元の変換で Markdown にする。"""
    candidate = _load_candidate(
        request.path, config=request.config, lookup=terminal_lookup(handlers.terminal)
    )
    source = candidate.source
    if source is None:
        count = len(candidate.violations) + len(candidate.script_violations)
        raise ValidationFailedError(
            message=f"{candidate.root}: 配信元の設定に違反が {count} 件あります",
            violations=[*candidate.violations, *candidate.script_violations],
            next_steps=["check_project で違反を確認してください"],
        )
    # 配信元の外を指すファイルは断る（文書のパスは基準のフォルダから解く）
    file = normalize_path(source.root / request.file)
    if not file.is_relative_to(source.root):
        raise DocumentNotFoundError(
            message=f"{request.file}: 配信元の外です", missing=[request.file]
        )
    # ファイルが範囲に当たり、除外に当たらない最初の文書の行を引く
    relative = file.relative_to(source.root).as_posix()
    table = next(
        (row for row in source.config.documents if row.enabled and row.matches(relative)), None
    )
    not_matched = DocumentNotFoundError(
        message=f"{request.file}: 文書の種類の範囲に該当する文書がありません",
        missing=[request.file],
    )
    target = Target(source, source.root, None, None, "read")
    if table is None:
        # 当たる行が無ければ、本文のファイルが `file` の文書を持つ最初の行を引く
        table = next(
            (
                row
                for row in source.config.documents
                if row.enabled
                and row.body_file is not None
                and any(
                    document.body_path == relative
                    for document in handlers.store.load(target, kinds=[row.id]).documents
                )
            ),
            None,
        )
    if table is None:
        raise not_matched
    # 変換を持たない種類は Markdown にしない
    if table.converter is None:
        raise ConverterNotDefinedError(
            message=f"{table.id}: converters[] を指していない種類です", kind=table.id
        )
    documents = [
        document
        for document in handlers.store.load(target, kinds=[table.id]).documents
        if relative in (document.path, document.body_path)
    ]
    if not documents:
        raise not_matched
    # 配信中の変換の控えを汚さないよう、使い捨てのフォルダを控えの場所にして変換する
    with tempfile.TemporaryDirectory() as directory:
        converter = ConvertService(
            Path(directory), handlers.store, handlers.terminal.script_timeout_sec
        )
        converted = [converter.convert(target, document) for document in documents]
    for item in converted:
        if item.failure is not None:
            raise ConvertScriptError(
                message=f"{item.failure.reason}: {item.failure.detail}",
                script=item.failure.script or "",
            )
    return TryConvertResult(
        kind=table.id,
        converter=source.script("converters", table.converter).run[-1],
        markdown=DOCUMENT_SEPARATOR.join(item.markdown for item in converted),
    )


NAV_ITEM_SEPARATOR = " > "


def _nav_invalid_argument(index: int, rule: str, fix: str = "") -> InvalidArgumentError:
    """`operations[{index}]` の違反 1 件の `InvalidArgumentError` を作る。"""
    return InvalidArgumentError(
        message="引数が正しくありません: 1 件",
        violations=[Violation(path=f"operations[{index}]", rule=rule, fix=fix)],
    )


def _find_tab(
    tabs: list[MutableMapping[str, Any]], title: str, index: int
) -> MutableMapping[str, Any]:
    """名前でタブを引く（無ければ今のタブの名前を添えた `InvalidArgumentError`）。"""
    found = next((tab for tab in tabs if tab.get("title") == title), None)
    if found is None:
        names = "、".join(str(tab.get("title")) for tab in tabs) or "なし"
        raise _nav_invalid_argument(index, f"タブ {title} がありません", f"今のタブ: {names}")
    return found


def _find_group(
    items: list[Any], name: str, index: int
) -> tuple[list[Any], MutableMapping[str, Any]]:
    """名前で `group` を引き、親の並びとその項目を返す。"""
    found = next(
        (item for item in items if item.get("group") == name or item.get("title") == name), None
    )
    if found is None:
        names = "、".join(str(item["group"]) for item in items if "group" in item) or "なし"
        raise _nav_invalid_argument(index, f"group {name} がありません", f"今の group: {names}")
    if "group" not in found:
        raise _nav_invalid_argument(index, f"{name} は group ではありません")
    return items, found


def _apply_nav_operation(nav: dict[str, Any], operation: NavOperation, index: int) -> None:  # noqa: C901
    """`nav` の複製に操作 1 件を当てる。"""
    if operation.op in ("add", "update") and operation.value is None:
        raise _nav_invalid_argument(index, f"{operation.op} には value が要ります")
    tabs: list[MutableMapping[str, Any]] = nav.setdefault("tabs", [])
    value = copy.deepcopy(operation.value or {})
    if operation.item is None:
        if operation.op == "add":
            if any(tab.get("title") == operation.tab for tab in tabs):
                raise _nav_invalid_argument(index, f"タブ {operation.tab} は既にあります")
            tabs.append(value)
            return
        tab = _find_tab(tabs, operation.tab, index)
        if operation.op == "update":
            tab.update(value)
        else:
            tabs.remove(tab)
        return
    parent: list[Any] = _find_tab(tabs, operation.tab, index).setdefault("items", [])
    group: MutableMapping[str, Any] | None = None
    for name in operation.item.split(NAV_ITEM_SEPARATOR):
        if group is not None:
            parent = group.setdefault("items", [])
        parent, group = _find_group(parent, name, index)
    assert group is not None  # noqa: S101
    if operation.op == "add":
        children: list[Any] = group.setdefault("items", [])
        if "group" in value and any(item.get("group") == value["group"] for item in children):
            raise _nav_invalid_argument(index, f"group {value['group']} は既にあります")
        children.append(value)
    elif operation.op == "update":
        group.update(value)
    else:
        parent.remove(group)


def _overlaid_nav(handlers: Handlers, config_file: Path) -> Path | None:
    """`config` の先頭が同じ `project-index.yaml` の行で、`nav` を持つ 2 つ目以降のファイルを返す。"""
    for entry in handlers.terminal.sources:
        if normalize_path(entry.config[0]) != config_file:
            continue
        for extra in entry.config[1:]:
            path = normalize_path(extra)
            try:
                value = load_yaml(path.read_text(encoding="utf-8"), file=str(path))
            except OSError, UnicodeDecodeError, YamlLoadError:
                continue
            if isinstance(value, dict) and "nav" in value:
                return path
    return None


def _nav_documents(handlers: Handlers, source: ServedSource) -> tuple[list[Any], dict[str, str]]:
    """配信元の文書と、行ごとの文書に当てるスキーマから使える項目を返す。"""
    target = Target(source, source.root, None, None, "read")
    documents = handlers.store.load(target).documents
    fields = known_fields(
        handlers.store.row_schema(target, row.id) for row in source.config.documents if row.enabled
    )
    return documents, fields


def write_nav(request: WriteNavRequest, *, handlers: Handlers) -> WriteNavResult:
    """`project-index.yaml` の `nav` のタブと group を名前で指して追加・修正・削除する。"""
    target = normalize_path(request.path)
    root = target.parent if target.suffix == ".yaml" else target
    config_file = _config_file(root)
    if not config_file.is_file():
        raise ConfigNotFoundError(
            message=f"配信元の設定がありません: {config_file}",
            path=str(config_file),
            next_steps=["/project-index:setup で配信元を追加してください"],
        )
    try:
        doc = load_roundtrip(config_file.read_text(encoding="utf-8"), file=str(config_file))
    except YamlLoadError as error:
        raise ConfigParseError(
            message=f"配信元の設定を読み込めません: {config_file}（{error}）",
            line=error.line,
            column=error.column,
        ) from error
    overlaid = _overlaid_nav(handlers, config_file)
    if overlaid is not None:
        raise InvalidArgumentError(
            message="引数が正しくありません: 1 件",
            violations=[
                Violation(
                    path="path",
                    rule=(
                        f"重ねた設定のファイル {overlaid} が nav を持つため、"
                        "配信に出るのはそちらの nav です"
                    ),
                    fix="重ねた設定のファイルの nav を削除してください",
                )
            ],
        )
    current = doc.get("nav")
    nav: dict[str, Any] = (
        json.loads(json.dumps(current)) if isinstance(current, Mapping) else {"tabs": []}
    )
    for index, operation in enumerate(request.operations):
        _apply_nav_operation(nav, operation, index)
    doc["nav"] = nav
    text = dump_roundtrip(doc)
    # 書いた後の設定を使い捨てのフォルダに置き、配信元を組み立てて確かめる
    with tempfile.TemporaryDirectory() as directory:
        file = Path(directory) / CONFIG_FILE
        file.write_text(text, encoding="utf-8")
        source, _, violations = assemble_source(
            [file],
            source_id=None,
            scope_read=[],
            scope_write=None,
            root_override=root,
            lookup=terminal_lookup(handlers.terminal),
        )
    nav_violations = [
        item for item in violations if item.path == "nav" or item.path.startswith("nav.")
    ]
    documents: list[Any] = []
    fields: dict[str, str] = {}
    if source is not None:
        documents, fields = _nav_documents(handlers, source)
        nav_violations.extend(
            check_nav_filters(
                nav,
                table_ids=[row.id for row in source.config.documents if row.enabled],
                fields=fields,
            )
        )
    if nav_violations:
        raise NavInvalidError(
            message=f"画面の構成が正しくありません: {len(nav_violations)} 件",
            violations=nav_violations,
        )
    replace_file(config_file, text)
    counts = nav_auto_counts(nav, documents, fields=fields, today=date.today())  # noqa: DTZ011
    return WriteNavResult(
        path=str(config_file),
        nav=dump_roundtrip(CommentedMap(nav)),
        counts=counts,
        warnings=zero_count_warnings(counts),
    )

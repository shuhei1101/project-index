"""配信元の読み込みと検証。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from jsonschema.exceptions import SchemaError
from jsonschema.validators import Draft202012Validator

from project_index.features.history.query import export_paths_at, read_file_at, resolve_ref
from project_index.features.settings.query import config_path, load_terminal_config
from project_index.features.settings.types import SourceEntry, TerminalConfigInvalidError
from project_index.features.sources.merge import merge_configs
from project_index.features.sources.schema_ref import (
    RefSchema,
    SchemaRef,
    SchemaRefError,
    SchemaRefLookup,
    read_schema_ref,
    terminal_lookup,
)
from project_index.features.sources.types import (
    SOURCE_CONFIG_VERSION,
    DocumentTable,
    ScriptEntry,
    ServedSource,
    SourceConfig,
    SourceStatus,
)
from project_index.integrations.git import is_ignored, main_repo_root
from project_index.integrations.git import repo_root as git_repo_root
from project_index.integrations.scripts import ScriptNotFoundError, check_runnable
from project_index.shared.errors import ProjectIndexError, ValidationFailedError, Violation
from project_index.shared.narrowing import is_dict
from project_index.shared.paths import normalize_path
from project_index.shared.schema_check import schema_violations
from project_index.shared.yaml_io import YamlLoadError, load_yaml

logger = logging.getLogger(__name__)

SOURCE_SCHEMA = "schemas/project-index.schema.yaml"
SCRIPT_TABLES = ("validators", "converters", "generators")

__all__ = [
    "SOURCE_CONFIG_VERSION",
    "SOURCE_SCHEMA",
    "assemble_source",
    "build_source_config",
    "check_scripts",
    "compare_config_version",
    "load_source",
    "load_source_at",
    "read_default_ref_config",
    "source_schema_json",
    "validate_source_config",
]


def _source_schema() -> dict[str, Any]:
    """配布に同梱した配信元の設定のスキーマを読む。"""
    text = resources.files("project_index").joinpath(SOURCE_SCHEMA).read_text(encoding="utf-8")
    # 同梱したスキーマの最上位は、キーが文字列の辞書
    return cast("dict[str, Any]", load_yaml(text))


def _as_schema(value: object) -> dict[str, Any]:
    """読んだスキーマを、キーを文字列とする辞書として返す（辞書でなければ空の辞書）。"""
    return cast("dict[str, Any]", value) if is_dict(value) else {}


def source_schema_json() -> str:
    """配信元の設定のスキーマを、配布する JSON Schema の文字列にする。"""
    return json.dumps(_source_schema(), ensure_ascii=False, indent=2) + "\n"


def _outside_root(pattern: str) -> bool:
    """パスが `..` で配信元の外を指すか。"""
    return ".." in Path(pattern).parts


ReadText = Callable[[str], str | None]


def _disk_reader(root: Path) -> ReadText:
    """配信元の直下からの相対パスのファイルをディスクから読む関数。"""

    def _read(relative: str) -> str | None:
        target = root / relative
        return target.read_text(encoding="utf-8") if target.is_file() else None

    return _read


def _commit_reader(root: Path, repo: Path, commit: str) -> ReadText:
    """配信元の直下からの相対パスのファイルを commit から読む関数。"""
    prefix = root.relative_to(repo) if root.is_relative_to(repo) else Path()

    def _read(relative: str) -> str | None:
        return read_file_at(repo, commit, (PurePosixPath(prefix.as_posix()) / relative).as_posix())

    return _read


def _file_violation(
    read_text: ReadText, key_path: str, relative: str, what: str
) -> Violation | None:
    """設定が指すファイルが配信元の下にあり、YAML として解析できるかを確かめる。"""
    if _outside_root(relative):
        return Violation(path=key_path, rule=f"配信元の外を指しています: {relative}")
    text = read_text(relative)
    if text is None:
        return Violation(path=key_path, rule=f"{what}のファイルが無い: {relative}")
    try:
        load_yaml(text, file=relative)
    except YamlLoadError as error:
        return Violation(path=key_path, rule=f"{what}を YAML として読み込めない: {error}")
    return None


type ReadRef = Callable[[SchemaRef], RefSchema]


def _settings_lookup() -> SchemaRefLookup:
    """端末の設定のファイルから参照先の配信元の引き当てを作る（読めなければ何も引けない）。"""
    try:
        terminal = load_terminal_config(config_path(os.environ))
    except TerminalConfigInvalidError:
        return lambda _source_id: None
    return terminal_lookup(terminal)


def _ref_reader(lookup: SchemaRefLookup | None) -> ReadRef:
    """参照先のスキーマを 1 回の組み立ての中で 1 回だけ読む関数を返す。"""
    resolved: list[SchemaRefLookup] = [lookup] if lookup is not None else []
    cache: dict[SchemaRef, RefSchema] = {}

    def _read(ref: SchemaRef) -> RefSchema:
        # 端末の設定は、参照の行を初めて読むときだけ読む
        if not resolved:
            resolved.append(_settings_lookup())
        if ref not in cache:
            cache[ref] = read_schema_ref(ref, lookup=resolved[0])
        return cache[ref]

    return _read


def validate_source_config(
    value: dict[str, Any], *, root: Path, lookup: SchemaRefLookup | None = None
) -> list[Violation]:
    """マージした設定をスキーマ・行の参照・ファイルの有無で確かめ、違反を全て返す。"""
    return _validate(value, _disk_reader(root), _ref_reader(lookup), root)


def _schema_violation(
    read_text: ReadText,
    read_ref: ReadRef,
    index: int,
    value: object,
) -> Violation | None:
    """行の `schema` が読めて JSON Schema として正しいかを確かめる。"""
    key_path = f"documents[{index}].schema"
    # 相対パスは配信元の下のファイルを読む
    if isinstance(value, str):
        found = _file_violation(read_text, key_path, value, "スキーマ")
        return found if found is not None else _check_schema_file(read_text, key_path, value)
    # オブジェクトはほかの配信元のリビジョンのスキーマを読む
    try:
        schema = read_ref(SchemaRef.model_validate(value)).schema
    except SchemaRefError as error:
        return Violation(path=key_path, rule=error.rule)
    return _check_schema(key_path, schema)


def _validate(
    value: dict[str, Any], read_text: ReadText, read_ref: ReadRef, config_root: Path
) -> list[Violation]:
    """配信元の設定の検証を、ファイルを `read_text` で読んで行う。"""
    violations = schema_violations(_source_schema(), value)
    # スキーマの違反があれば、ここで返す
    if violations:
        return violations
    documents: list[dict[str, Any]] = value.get("documents", [])
    # テーブルごとに ID の重なりを確かめる
    tables = {"documents": documents}
    tables.update({name: value.get(name, []) for name in SCRIPT_TABLES})
    for name, rows in tables.items():
        violations.extend(_duplicate_ids(name, rows))
    ids = {name: {row["id"] for row in value.get(name, [])} for name in SCRIPT_TABLES}
    for index, row in enumerate(documents):
        violations.extend(_document_row_violations(index, row, ids))
        found = _schema_violation(read_text, read_ref, index, row["schema"])
        if found is not None:
            violations.append(found)
    violations.extend(_paths_base_violations(value.get("paths_base"), config_root))
    return violations


def _duplicate_ids(name: str, rows: list[dict[str, Any]]) -> list[Violation]:
    """テーブルの行の ID の重なりを違反にする。"""
    violations: list[Violation] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if row["id"] in seen:
            violations.append(
                Violation(path=f"{name}[{index}].id", rule=f"ID が重なっています: {row['id']}")
            )
        seen.add(row["id"])
    return violations


# `documents[]` の行の参照のキーと、参照先のテーブル
REFERENCES = (
    ("validators", "validators"),
    ("converter", "converters"),
    ("after_write", "generators"),
)


def _document_row_violations(
    index: int, row: dict[str, Any], ids: dict[str, set[str]]
) -> list[Violation]:
    """`documents[]` の 1 行の、無い ID への参照・`body_file` の単独の記載・配信元の外を指すパスを違反にする。"""
    violations: list[Violation] = []
    for key, table in REFERENCES:
        refs = row.get(key, [])
        targets = [refs] if isinstance(refs, str) else refs
        for position, ref in enumerate(targets):
            if ref in ids[table]:
                continue
            # converter は 1 つの ID、それ以外は ID の配列
            path = f"documents[{index}].{key}" + ("" if key == "converter" else f"[{position}]")
            violations.append(
                Violation(
                    path=path, rule="存在しない ID", fix=f"{table}[] の ID を指してください: {ref}"
                )
            )
    if "body_file" in row and "records" not in row:
        violations.append(
            Violation(path=f"documents[{index}].body_file", rule="records と一緒に記載してください")
        )
    violations.extend(
        Violation(
            path=f"documents[{index}].paths[{position}]",
            rule=f"配信元の外を指しています: {pattern}",
        )
        for position, pattern in enumerate(row["paths"])
        if _outside_root(pattern)
    )
    return violations


def _paths_base_violations(value: str | None, config_root: Path) -> list[Violation]:
    """`paths_base` が範囲の中かを確かめる（省いた設定はリポジトリの直下を求めずに返す）。"""
    if value is None:
        return []
    _, violations = _resolve_paths_base(value, config_root, git_repo_root(config_root))
    return violations


def _resolve_paths_base(
    value: str | None, config_root: Path, repo_root: Path | None
) -> tuple[Path, list[Violation]]:
    """`paths_base` を設定ファイルのフォルダから解き、範囲を確かめて基準のフォルダを返す。"""
    # 省いた設定: 設定ファイルのフォルダを基準にする
    if value is None:
        return config_root, []
    base = normalize_path(config_root / value)
    violations: list[Violation] = []
    # 無いフォルダ
    if not base.is_dir():
        violations.append(Violation(path="paths_base", rule=f"フォルダがありません: {value}"))
    # 設定ファイルのフォルダの下や横: 上のフォルダだけを基準にできる
    if not config_root.is_relative_to(base):
        violations.append(
            Violation(
                path="paths_base",
                rule=f"設定ファイルのフォルダかそれより上のフォルダを指してください: {value}",
            )
        )
    # Git の配信元でリポジトリの直下より上: default_ref の commit から読めない
    if repo_root is not None and not base.is_relative_to(repo_root):
        violations.append(
            Violation(path="paths_base", rule=f"リポジトリの外を指しています: {value}")
        )
    if violations:
        return config_root, violations
    return base, []


def _check_schema_file(read_text: ReadText, key_path: str, relative: str) -> Violation | None:
    """スキーマのファイルが JSON Schema（Draft 2020-12）として正しいかを確かめる。"""
    return _check_schema(key_path, load_yaml(read_text(relative) or ""))


def _check_schema(key_path: str, schema: object) -> Violation | None:
    """スキーマが JSON Schema（Draft 2020-12）として正しいかを確かめる。"""
    try:
        # 辞書・真偽値でない値も、メタスキーマの検査に渡して SchemaError の理由を得る
        Draft202012Validator.check_schema(cast("Any", schema))
    except SchemaError as error:
        return Violation(path=key_path, rule=f"スキーマが正しくありません: {error.message}")
    return None


def check_scripts(config: SourceConfig, *, root: Path) -> list[Violation]:
    """検査・変換・生成の行のコマンドを動かさずに確かめる。"""
    violations: list[Violation] = []
    for table in SCRIPT_TABLES:
        for index, row in enumerate(getattr(config, table)):
            try:
                check_runnable(row.run, cwd=root)
            except ScriptNotFoundError as error:
                violations.append(Violation(path=f"{table}[{index}]", rule=error.reason))
    return violations


def _check_scripts_at(config: SourceConfig, root: Path, repo: Path, commit: str) -> list[Violation]:
    """スクリプトのファイルが commit にあるかを、そのリビジョンから取り出したフォルダで確かめる。"""
    prefix = PurePosixPath(root.relative_to(repo).as_posix()) if root.is_relative_to(repo) else None
    folders = _script_folders(config, prefix, repo, commit)
    if not folders:
        with tempfile.TemporaryDirectory() as empty:
            return check_scripts(config, root=Path(empty))
    with export_paths_at(repo, commit, sorted(folders)) as exported:
        return check_scripts(config, root=exported / (prefix or PurePosixPath()).as_posix())


def _script_folders(
    config: SourceConfig, prefix: PurePosixPath | None, repo: Path, commit: str
) -> set[str]:
    """行のコマンドの引数のうち、commit にあるファイルを持つフォルダを集める。"""
    if prefix is None:
        return set()
    # オプション（`-` で始まる）と絶対パスはファイルを指さない
    relatives = [
        (prefix / item).as_posix()
        for table in SCRIPT_TABLES
        for row in getattr(config, table)
        for item in row.run
        if not item.startswith(("-", "/"))
    ]
    return {
        PurePosixPath(relative).parent.as_posix()
        for relative in relatives
        if read_file_at(repo, commit, relative) is not None
    }


def compare_config_version(version: str) -> Literal["same", "older", "newer"]:
    """配信元の設定のバージョンをサーバーの参照できるバージョンと比べる。"""
    mine, current = int(version), int(SOURCE_CONFIG_VERSION)
    if mine == current:
        return "same"
    return "older" if mine < current else "newer"


def build_source_config(value: dict[str, Any]) -> SourceConfig:
    """検証を通した設定の値から `SourceConfig` を作る。"""
    ids = value.get("ids", {})
    related = value.get("related", {})
    diff = value.get("diff", {})
    github = value.get("github", {})
    decisions = value.get("decisions", {})
    options: dict[str, Any] = {}
    for key in (
        "version",
        "enabled",
        "default_ref",
        "paths_base",
        "visibility",
        "worktrees",
        "nav",
    ):
        if key in value:
            options[key] = value[key]
    if "types" in related:
        options["related_types"] = list(related["types"])
    if "ignore_keys" in diff:
        options["diff_ignore_keys"] = list(diff["ignore_keys"])
    if "repository" in github:
        options["github_repository"] = github["repository"]
    if "issue_labels" in github:
        options["github_issue_labels"] = list(github["issue_labels"])
    if "format" in ids:
        options["ids_format"] = ids["format"]
    if "folders" in decisions:
        options["decision_folders"] = list(decisions["folders"])
    return SourceConfig(
        name=value["name"],
        description=value.get("description", ""),
        instructions=value.get("instructions", ""),
        when=list(value.get("when", [])),
        documents=[_build_table(row) for row in value.get("documents", [])],
        validators=[_build_script(row) for row in value.get("validators", [])],
        converters=[_build_script(row) for row in value.get("converters", [])],
        generators=[_build_script(row) for row in value.get("generators", [])],
        **options,
    )


def _build_script(row: dict[str, Any]) -> ScriptEntry:
    """スクリプトの行を作る。"""
    return ScriptEntry(
        id=row["id"],
        run=list(row["run"]),
        on=list(row.get("on", ["write"])),
        cache=bool(row.get("cache", True)),
    )


def _build_table(row: dict[str, Any]) -> DocumentTable:
    """文書の行を作る。"""
    return DocumentTable(
        id=row["id"],
        paths=list(row["paths"]),
        schema_path=row["schema"] if isinstance(row["schema"], str) else SchemaRef(**row["schema"]),
        title=row.get("title"),
        enabled=row.get("enabled", True),
        validators=list(row.get("validators", [])),
        converter=row.get("converter"),
        writable=row.get("writable"),
        after_write=list(row.get("after_write", [])),
        search=row.get("search", True),
        records=row.get("records"),
        body_file=row.get("body_file"),
        metadata=dict(row.get("metadata", {})),
        exclude=list(row.get("exclude", [])),
        alias_type=row.get("alias_type"),
    )


def _read_configs(
    files: list[Path], first_text: str | None = None
) -> tuple[list[dict[str, Any]], list[Violation]]:
    """設定の YAML を順に読む。無い・読めない・辞書でないファイルは違反にする。"""
    values: list[dict[str, Any]] = []
    violations: list[Violation] = []
    for index, file in enumerate(files):
        path = f"config[{index}]"
        if index == 0 and first_text is not None:
            text = first_text
        elif file.is_file():
            text = file.read_text(encoding="utf-8")
        else:
            violations.append(Violation(path=path, rule=f"設定のファイルが無い: {file}"))
            continue
        try:
            value = load_yaml(text, file=str(file))
        except YamlLoadError as error:
            violations.append(Violation(path=path, rule=f"YAML として読み込めない: {error}"))
            continue
        if not is_dict(value):
            violations.append(Violation(path=path, rule=f"最上位が辞書ではない: {file}"))
            continue
        values.append(cast("dict[str, Any]", value))
    return values, violations


def _worktree_globs(patterns: list[str], base: Path) -> list[str]:
    """`worktrees` の glob を、リポジトリの直下からの絶対パスにする。"""
    result: list[str] = []
    for pattern in patterns:
        expanded = Path(pattern).expanduser()
        joined = expanded if expanded.is_absolute() else base / expanded
        result.append(os.path.normpath(joined.as_posix()))
    return result


def read_default_ref_config(first: Path) -> tuple[str, str] | None:
    """ディスクの先頭の設定の `default_ref` を読み、そのリビジョンの先頭の設定の commit と内容を返す。"""
    top = git_repo_root(first.parent)
    if top is None:
        return None
    try:
        value = load_yaml(first.read_text(encoding="utf-8"), file=str(first))
    except OSError, YamlLoadError:
        value = None
    configured = value.get("default_ref") if is_dict(value) else None
    default_ref = configured if isinstance(configured, str) else SourceConfig.default_ref
    try:
        commit = resolve_ref(top, default_ref, date_base=default_ref, argument="default_ref").commit
    except ProjectIndexError as error:
        rule = f"{default_ref} を解けません"
        raise ValidationFailedError(
            message=rule, violations=[Violation(path="default_ref", rule=rule)]
        ) from error
    relative = Path(os.path.abspath(first)).relative_to(top).as_posix()
    text = read_file_at(top, commit, relative)
    if text is None and first.is_file() and is_ignored(first, top):
        # どのブランチにも入らない設定は、ディスクの内容で組み立てる
        text = first.read_text(encoding="utf-8")
    if text is None:
        rule = f"{default_ref} に {relative} がありません"
        raise ValidationFailedError(
            message=rule, violations=[Violation(path="config[0]", rule=rule)]
        )
    return commit, text


def assemble_source(
    files: list[Path],
    *,
    source_id: str | None,
    scope_read: list[str],
    scope_write: list[str] | None,
    outside_read: bool = True,
    root_override: Path | None = None,
    lookup: SchemaRefLookup | None = None,
) -> tuple[ServedSource | None, SourceConfig | None, list[Violation]]:
    """設定を読み、マージ・検証・スクリプトの確かめをして、配信中の配信元を作る。"""
    return _assemble(
        files,
        source_id=source_id,
        scope_read=scope_read,
        scope_write=scope_write,
        outside_read=outside_read,
        root_override=root_override,
        lookup=lookup,
    )


def _assemble(
    files: list[Path],
    *,
    source_id: str | None,
    scope_read: list[str],
    scope_write: list[str] | None,
    outside_read: bool,
    root_override: Path | None = None,
    at: tuple[str, str] | None = None,
    lookup: SchemaRefLookup | None = None,
) -> tuple[ServedSource | None, SourceConfig | None, list[Violation]]:
    """配信元の組み立て。`at` は（`default_ref` の commit, そのリビジョンの先頭の設定の内容）。"""
    values, violations = _read_configs(files, at[1] if at else None)
    if violations:
        return None, None, violations
    root = root_override or files[0].parent
    top = git_repo_root(root)
    commit = at[0] if at and top is not None else None
    read_text = _commit_reader(root, top, commit) if top and commit else _disk_reader(root)
    merged = merge_configs(values)
    read_ref = _ref_reader(lookup)
    violations = _validate(merged, read_text, read_ref, root)
    if violations:
        return None, None, violations
    config = build_source_config(merged)
    if top is not None and commit is not None:
        violations = _check_scripts_at(config, root, top, commit)
    else:
        violations = check_scripts(config, root=root)
    if violations:
        return None, config, violations
    main_root = main_repo_root(root) if top is not None else None
    base = main_root or top or root
    # 文書の基準のフォルダ（範囲は検証で確かめてある）。設定ファイルのフォルダはそこからの相対パスで持つ
    docs_root, _ = _resolve_paths_base(config.paths_base, root, top)
    schemas = _row_schemas(config, read_text, read_ref)
    served = ServedSource(
        id=source_id or config.name,
        root=docs_root,
        config_files=files,
        config=config,
        is_git=top is not None,
        repo_root=top,
        scope_read=list(scope_read),
        scope_write=list(scope_write) if scope_write else [str(root)],
        worktree_globs=_worktree_globs(config.worktrees, base),
        schemas=schemas,
        main_root=main_root,
        config_commit=commit,
        outside_read=outside_read,
        config_dir=PurePosixPath(root.relative_to(docs_root).as_posix()),
    )
    return served, config, []


def _row_schemas(
    config: SourceConfig, read_text: ReadText, read_ref: ReadRef
) -> dict[str, dict[str, Any]]:
    """種類の行ごとのスキーマを読む（ほかの配信元の参照は、検証で読んだ `$ref` まで解いたスキーマ）。"""
    return {
        row.id: _as_schema(load_yaml(read_text(row.schema_path) or ""))
        if isinstance(row.schema_path, str)
        else read_ref(row.schema_path).schema
        for row in config.documents
    }


def _log_violations(source_id: str, violations: list[Violation]) -> None:
    """配信しない理由を、違反ごとに `{id}: {パス}: {理由}` でエラーログに書く。"""
    for violation in violations:
        logger.error("%s: %s: %s", source_id, violation.path, violation.rule)


def _declared_version(files: list[Path]) -> str | None:
    """マージした設定が書いている `version`。読めない・書いていなければ `None`。"""
    values, violations = _read_configs(files)
    if violations:
        return None
    version = merge_configs(values).get("version")
    return version if isinstance(version, str) and version.isdecimal() else None


def entry_source_id(entry: SourceEntry) -> str | None:
    """端末の設定の 1 行が指す配信元の ID（`id`、無ければディスクの設定を重ねた `name`）を返す。"""
    if entry.id is not None:
        return entry.id
    # 読めない設定のファイルは飛ばし、読めたファイルだけを重ねる
    values, _ = _read_configs([Path(item).expanduser() for item in entry.config])
    name = merge_configs(values).get("name") if values else None
    return name if isinstance(name, str) else None


def load_source(
    entry: SourceEntry, *, index: int, lookup: SchemaRefLookup | None = None
) -> tuple[ServedSource | None, SourceStatus]:
    """端末の設定の 1 行から配信元の設定を読んで検証し、配信中の配信元と状態を作る。"""
    fallback_id = entry.id or f"sources[{index}]"
    config_files = tuple(entry.config)
    # 端末の設定で無効な行は、設定を読まない
    if not entry.enabled:
        return None, SourceStatus(
            id=fallback_id, index=index, status="disabled", config=config_files
        )
    files = [Path(item).expanduser() for item in entry.config]
    try:
        at = read_default_ref_config(files[0])
    except ValidationFailedError as error:
        _log_violations(fallback_id, error.violations)
        return None, SourceStatus(
            id=fallback_id,
            index=index,
            status="not_served",
            errors=error.violations,
            config=config_files,
        )
    served, config, violations = _assemble(
        files,
        source_id=entry.id,
        scope_read=entry.scope.read,
        scope_write=entry.scope.write,
        outside_read=entry.outside_read,
        at=at,
        lookup=lookup,
    )
    source_id = entry.id or (config.name if config else fallback_id)
    if violations:
        _log_violations(source_id, violations)
        declared = _declared_version(files)
        if declared is not None and compare_config_version(declared) == "older":
            logger.error(
                "%s: 設定のバージョンが古いので、project-index migrate --source %s で移し替えられます",
                source_id,
                files[0],
            )
        return None, SourceStatus(
            id=source_id, index=index, status="not_served", errors=violations, config=config_files
        )
    if served is None or config is None:
        msg = "配信元の設定が読めていません"
        raise RuntimeError(msg)
    # 配信元の設定で無効
    if not config.enabled:
        return None, SourceStatus(id=source_id, index=index, status="disabled", config=config_files)
    # 設定のバージョンを比べる
    comparison = compare_config_version(config.version)
    if comparison == "newer":
        violations = [Violation(path="version", rule="このサーバーより新しい設定です")]
        _log_violations(source_id, violations)
        return None, SourceStatus(
            id=source_id, index=index, status="not_served", errors=violations, config=config_files
        )
    config_version: tuple[str, str] | None = None
    if comparison == "older":
        config_version = (config.version, SOURCE_CONFIG_VERSION)
        logger.warning(
            "配信元の設定のバージョンが古い（%s・設定 %s・サーバーが参照できる %s）",
            source_id,
            config.version,
            SOURCE_CONFIG_VERSION,
        )
    return served, SourceStatus(
        id=source_id,
        index=index,
        status="serving",
        config_version=config_version,
        config=config_files,
    )


def load_source_at(source: ServedSource, root: Path) -> ServedSource:
    """配信中の配信元の設定を、作業ツリーかワークツリーの同じ場所から読み直す。"""
    base = source.repo_root or source.root
    files: list[Path] = []
    for file in source.config_files:
        try:
            target = root / file.relative_to(base)
        except ValueError:
            # 配信元のリポジトリの外のファイルはそのまま使う
            files.append(file)
            continue
        # 無視されている設定はワークツリーに無いので、クローン本体のファイルを使う
        if not target.is_file() and source.repo_root and is_ignored(file, source.repo_root):
            files.append(file)
            continue
        files.append(target)
    # 設定ファイルのフォルダを、作業ツリー・ワークツリーの同じ場所に置き換える
    config_root = source.config_root
    relative_root = config_root.relative_to(base) if config_root.is_relative_to(base) else Path()
    served, _, violations = assemble_source(
        files,
        source_id=source.id,
        scope_read=source.scope_read,
        scope_write=source.scope_write,
        outside_read=source.outside_read,
        root_override=root / relative_root,
    )
    if violations or served is None:
        raise ValidationFailedError(
            message="; ".join(f"{source.id}: {v.path}: {v.rule}" for v in violations),
            violations=violations,
        )
    return served

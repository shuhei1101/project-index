"""配信元の設定と配信中の配信元の型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from project_index.features.sources.schema_ref import SchemaRef
from project_index.shared.errors import UnknownKindError, Violation

SOURCE_CONFIG_VERSION = "3"

type SourceStatusKind = Literal["serving", "not_served", "disabled"]


@dataclass(frozen=True)
class DocumentTable:
    """配信元の設定の `documents[]` の 1 行。"""

    id: str
    paths: list[str]
    # 文字列は配信元の直下からの相対パス、`SchemaRef` はほかの配信元のリビジョンのスキーマ
    schema_path: str | SchemaRef
    title: str | None = None
    enabled: bool = True
    validators: list[str] = field(default_factory=list[str])
    converter: str | None = None
    writable: bool | None = None
    after_write: list[str] = field(default_factory=list[str])
    search: bool = True
    records: str | None = None
    body_file: str | None = None
    metadata: dict[str, str] = field(default_factory=dict[str, str])
    exclude: list[str] = field(default_factory=list[str])
    alias_type: str | None = None

    @property
    def is_writable(self) -> bool:
        """`write_docs`・`delete_docs` を許すか（`writable` が無ければ許す）。"""
        return True if self.writable is None else self.writable

    def excludes(self, path: str) -> bool:
        """ファイル名（パスの末尾の要素）が `exclude` のどれかに当たるか。"""
        name = PurePosixPath(PurePosixPath(path).name)
        return any(name.full_match(pattern) for pattern in self.exclude)

    def matches(self, path: str) -> bool:
        """ファイルがこの行の文書になるか（`paths` に当たり、`exclude` に当たらない）。"""
        target = PurePosixPath(path)
        in_paths = any(target.full_match(pattern) for pattern in self.paths)
        return in_paths and not self.excludes(path)


@dataclass(frozen=True)
class ScriptEntry:
    """`validators[]`・`converters[]`・`generators[]` の 1 行。"""

    id: str
    run: list[str]
    on: list[Literal["read", "write"]] = field(default_factory=lambda: ["write"])
    # `converters[]` だけが使う。False の行の変換は控えを読まず書かない
    cache: bool = True


@dataclass(frozen=True)
class SourceConfig:
    """マージして検証を通した配信元の設定。"""

    name: str
    version: str = SOURCE_CONFIG_VERSION
    enabled: bool = True
    default_ref: str = "develop"
    # `documents[].paths` の基準のフォルダ（設定ファイルのフォルダからの相対パス）。`None` は設定ファイルのフォルダ
    paths_base: str | None = None
    visibility: dict[str, Any] | None = None
    worktrees: list[str] = field(default_factory=lambda: ["./.claude/worktrees/*"])
    documents: list[DocumentTable] = field(default_factory=list[DocumentTable])
    validators: list[ScriptEntry] = field(default_factory=list[ScriptEntry])
    converters: list[ScriptEntry] = field(default_factory=list[ScriptEntry])
    generators: list[ScriptEntry] = field(default_factory=list[ScriptEntry])
    nav: dict[str, Any] | None = None
    ids_format: str | None = None
    related_types: list[str] = field(
        default_factory=lambda: ["references", "depends_on", "see_also", "implements", "tests"]
    )
    diff_ignore_keys: list[str] = field(default_factory=lambda: ["updated"])
    github_repository: str | None = None
    github_issue_labels: list[str] = field(default_factory=list[str])
    # `decisions.folders`。設計書の `decisions` の検討事項の文書を探す話し合いの記録のフォルダ
    decision_folders: list[str] = field(default_factory=list[str])
    description: str = ""
    instructions: str = ""
    # 使う場面（どういうときにこの配信元で検索するか）の行
    when: list[str] = field(default_factory=list[str])


@dataclass(frozen=True)
class ServedSource:
    """検証を通した 1 つの配信元と、読み書きに要る解いた値。"""

    id: str
    # `documents[].paths` と返却する文書のパスの基準のフォルダ
    root: Path
    config_files: list[Path]
    config: SourceConfig
    is_git: bool
    repo_root: Path | None
    scope_read: list[str]
    scope_write: list[str]
    worktree_globs: list[str]
    schemas: dict[str, dict[str, Any]]
    main_root: Path | None = None
    config_commit: str | None = None
    outside_read: bool = True
    # `root` から先頭の設定の YAML のフォルダへの相対パス。`paths_base` を省いた配信元は `.`
    config_dir: PurePosixPath = field(default_factory=PurePosixPath)

    @property
    def config_root(self) -> Path:
        """先頭の設定の YAML のフォルダを返す。"""
        return self.root / self.config_dir

    def config_path(self, relative: str) -> str:
        """設定ファイルのフォルダからの相対パスを、`root` からの相対パスにする。"""
        return (self.config_dir / relative).as_posix()

    def table(self, kind: str) -> DocumentTable:
        """種類から有効な文書の行を引く。"""
        enabled = [row for row in self.config.documents if row.enabled]
        for row in enabled:
            if row.id == kind:
                return row
        raise UnknownKindError(
            message=f"{self.id}: 種類 {kind} はありません",
            kinds=[row.id for row in enabled],
            next_steps=["describe(source) で種類の一覧を確認してください"],
        )

    def script(
        self, table: Literal["validators", "converters", "generators"], script_id: str
    ) -> ScriptEntry:
        """検査・変換・生成の行を ID で引く。"""
        for row in getattr(self.config, table):
            if row.id == script_id:
                return row  # type: ignore[no-any-return]
        msg = f"{table}[{script_id}]"
        raise KeyError(msg)


@dataclass(frozen=True)
class SourceStatus:
    """端末の設定の 1 行が配信中か、外したならその理由。"""

    id: str
    index: int
    status: SourceStatusKind
    errors: list[Violation] = field(default_factory=list[Violation])
    config_version: tuple[str, str] | None = None
    config: tuple[str, ...] = ()

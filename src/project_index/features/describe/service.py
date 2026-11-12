"""`describe` の処理。"""

from __future__ import annotations

import dataclasses
from io import StringIO
from typing import TYPE_CHECKING, Any

from ruamel.yaml import YAML

from project_index.features.access.service import (
    available_sources,
    describe_workplace,
    outside_readable_sources,
    resolve_read_targets,
)
from project_index.features.describe.types import (
    DescribeRequest,
    KindSchemaResult,
    KindSummary,
    OutsideSource,
    SourceGuideResult,
    SourceListResult,
)
from project_index.features.describe.warnings import collect_warnings
from project_index.features.history.query import list_refs, list_worktrees
from project_index.features.sources.service import load_source_at
from project_index.shared.errors import InvalidArgumentError, Violation

if TYPE_CHECKING:
    from project_index.features.describe.source_checks import SourceChecks
    from project_index.features.documents.store import DocumentStore
    from project_index.features.settings.types import TerminalConfig
    from project_index.features.sources.registry import SourceRegistry


def _dump_yaml(value: dict[str, Any]) -> str:
    """スキーマを YAML の文字列にする。"""
    yaml = YAML(typ="safe", pure=True)
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    stream = StringIO()
    yaml.dump(value, stream)
    return stream.getvalue()


def describe(
    request: DescribeRequest,
    *,
    registry: SourceRegistry,
    store: DocumentStore,
    terminal: TerminalConfig,
    checks: SourceChecks,
) -> SourceListResult | SourceGuideResult | KindSchemaResult:
    """`describe` の要求を処理して結果を返す。"""
    if request.source is None:
        if request.kind is not None:
            raise InvalidArgumentError(
                message="kind には source が要ります",
                violations=[
                    Violation(
                        path="kind",
                        rule="kind には source が要ります",
                        fix="source も指定してください",
                    )
                ],
            )
        # outside_scope を渡したときだけ、作業範囲の外で読める配信元を添える
        outside_sources = (
            [
                OutsideSource(id=source.id, description=source.config.description)
                for source in outside_readable_sources(request.cwd, registry=registry)
            ]
            if request.outside_scope
            else None
        )
        available = available_sources(request.cwd, registry=registry)
        return SourceListResult(
            workplace=describe_workplace(request.cwd, registry=registry),
            sources=available,
            outside_sources=outside_sources,
            warnings=collect_warnings(
                available, registry=registry, checks=checks, terminal=terminal
            ),
        )
    target = resolve_read_targets(
        registry=registry,
        source=request.source,
        worktree=request.worktree,
        cwd=request.cwd,
        outside_scope=request.outside_scope,
    )[0]
    # 作業ツリーかワークツリーを読むときは、その場所の設定を読み直した配信元を使う
    if target.worktree is not None and target.ref is None:
        target = dataclasses.replace(target, source=load_source_at(target.source, target.worktree))
    source = target.source
    if request.kind is None:
        kinds: list[KindSummary] = []
        for table in source.config.documents:
            if not table.enabled:
                continue
            schema = store.schema(target, table.id)
            kinds.append(
                KindSummary(
                    id=table.id, description=str(schema.get("description") or table.title or "")
                )
            )
        refs: dict[str, list[str]] | None = None
        worktrees = None
        if source.is_git:
            listed = list_refs(source, commits=0)
            refs = {
                "branches": [item.name for item in listed.branches],
                "tags": [item.name for item in listed.tags],
            }
            worktrees = list_worktrees(source)
        return SourceGuideResult(
            source_id=source.id,
            instructions=source.config.instructions,
            kinds=kinds,
            outside_scope=target.outside_scope,
            refs=refs,
            worktrees=worktrees,
        )
    table = source.table(request.kind)
    schema = store.schema(target, table.id)
    schema_text = ""
    # ほかの配信元のリビジョンを指す行は、`$ref` まで解いたスキーマを YAML にして返す
    if not isinstance(table.schema_path, str):
        schema_text = _dump_yaml(schema)
    else:
        schema_file = store.read_root(target) / table.schema_path
        if schema_file.is_file():
            schema_text = schema_file.read_text(encoding="utf-8")
    return KindSchemaResult(
        source_id=source.id,
        kind=table.id,
        schema_text=schema_text,
        schema=schema,
        metadata=dict(table.metadata),
        outside_scope=target.outside_scope,
    )

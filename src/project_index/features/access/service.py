"""作業場所からの権限の判定と、読み書きする場所の解決。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from project_index.features.access.types import AccessLevel, SourceAccess, Target, Workplace
from project_index.features.history.query import resolve_ref
from project_index.features.sources.service import load_source_at
from project_index.shared.errors import (
    InvalidArgumentError,
    SourceNotReadableError,
    SourceNotWritableError,
    TargetIsCloneError,
    Violation,
    WorktreeNotMatchedError,
)
from project_index.shared.paths import match_glob, normalize_path

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from project_index.features.sources.registry import SourceRegistry
    from project_index.features.sources.types import ServedSource

logger = logging.getLogger(__name__)

MULTI_SOURCE_MIN = 2
DESCRIBE_HINT = "describe() で、今の作業場所から使用できる配信元を確認してください"
OUTSIDE_HINT = "outside_scope: true を指定すると、作業範囲の外（参考）として参照できます"


def _normalize(value: str | None) -> Path | None:
    """文字列の作業場所を正規化し、無ければ `None` にする。"""
    return normalize_path(value) if value else None


def find_worktree(source: ServedSource, path: Path) -> Path | None:
    """パスが配信元のどのワークツリーの中かを返す。"""
    # path 自身から親へ、深いほうから順に glob へ当てる
    for candidate in (path, *path.parents):
        if match_glob(candidate, source.worktree_globs):
            return candidate
    return None


def _base_of(source: ServedSource, worktree: Path | None) -> Path:
    """文書の相対パスを解くフォルダ（ワークツリーでは、リポジトリからの相対位置をつなぐ）。"""
    if worktree is None:
        return source.root
    if source.repo_root is not None and source.root.is_relative_to(source.repo_root):
        return worktree / source.root.relative_to(source.repo_root)
    return worktree


def access_of(source: ServedSource, cwd: Path | None) -> AccessLevel | None:
    """作業場所から配信元への権限を決める。"""
    if cwd is None:
        return None
    # ワークツリーの中は、配信元のフォルダにいるものとして照らす
    path = source.root if find_worktree(source, cwd) is not None else cwd
    if match_glob(path, source.scope_write):
        return "write"
    if match_glob(path, source.scope_read):
        return "read"
    return None


def current_source(
    sources: Sequence[ServedSource], cwd: Path | None
) -> tuple[ServedSource, Path | None] | None:
    """作業場所を含む配信元のうち、直下が一番深いものを返す。"""
    if cwd is None:
        return None
    best: tuple[ServedSource, Path | None] | None = None
    best_depth = -1
    for source in sources:
        worktree = find_worktree(source, cwd)
        candidate = worktree if worktree is not None else source.root
        if candidate != cwd and candidate not in cwd.parents:
            continue
        # 同じ深さは先の配信元を残す
        if len(candidate.parts) > best_depth:
            best, best_depth = (source, worktree), len(candidate.parts)
    return best


def available_sources(cwd: str | None, *, registry: SourceRegistry) -> list[SourceAccess]:
    """作業場所から使える配信元と権限を並べる。"""
    path = _normalize(cwd)
    sources = registry.served()
    current = current_source(sources, path)
    result: list[SourceAccess] = []
    for source in sources:
        access = access_of(source, path)
        if access is None:
            continue
        result.append(
            SourceAccess(
                source_id=source.id,
                access=access,
                current=current is not None and current[0].id == source.id,
                description=source.config.description,
            )
        )
    return result


def outside_readable_sources(cwd: str | None, *, registry: SourceRegistry) -> list[ServedSource]:
    """作業場所の `scope` に当たらず、`outside_read` が真の配信元を並べる。"""
    path = _normalize(cwd)
    return [
        source
        for source in registry.served()
        if access_of(source, path) is None and source.outside_read
    ]


def describe_workplace(cwd: str | None, *, registry: SourceRegistry) -> Workplace:
    """作業場所がどの配信元のクローン本体かワークツリーかを返す。"""
    path = _normalize(cwd)
    current = current_source(registry.served(), path)
    if current is None:
        return Workplace(cwd=path, source_id=None, worktree=None)
    return Workplace(cwd=path, source_id=current[0].id, worktree=current[1])


def _not_readable(
    source_id: str, cwd: str | None, registry: SourceRegistry, *, guide_outside: bool = False
) -> SourceNotReadableError:
    """読めない配信元のエラーを、使える配信元を添えて作る。"""
    return SourceNotReadableError(
        message=f"{source_id} はこの作業場所（{cwd}）から参照できません",
        available=available_sources(cwd, registry=registry),
        next_steps=[DESCRIBE_HINT, *([OUTSIDE_HINT] if guide_outside else [])],
    )


def _readable_sources(
    registry: SourceRegistry,
    source: str | list[str] | None,
    cwd: str | None,
    *,
    outside_scope: bool = False,
) -> list[tuple[ServedSource, bool]]:
    """読む配信元と作業範囲の外かを決める（権限の無い配信元は断る。`*` は黙って外す）。"""
    path = _normalize(cwd)
    if source is None:
        current = current_source(registry.served(), path)
        if current is None or access_of(current[0], path) is None:
            msg = "作業中の配信元"
            raise _not_readable(msg, cwd, registry)
        return [(current[0], False)]
    if source == "*":
        return [(item, False) for item in registry.served() if access_of(item, path) is not None]
    ids = [source] if isinstance(source, str) else source
    single = isinstance(source, str)
    result: list[tuple[ServedSource, bool]] = []
    for source_id in ids:
        item = registry.get(source_id)
        if access_of(item, path) is not None:
            result.append((item, False))
            continue
        if single and item.outside_read and outside_scope:
            logger.info("作業範囲の外を読んだ（cwd: %s・配信元: %s）", cwd, source_id)
            result.append((item, True))
            continue
        raise _not_readable(source_id, cwd, registry, guide_outside=single and item.outside_read)
    return result


def resolve_read_targets(
    *,
    registry: SourceRegistry,
    source: str | list[str] | None = None,
    ref: str | None = None,
    worktree: str | None = None,
    cwd: str | None = None,
    outside_scope: bool = False,
) -> list[Target]:
    """MCP の `source`・`ref`・`worktree`・`cwd` から、読む配信元ごとの場所を解く。"""
    path = _normalize(cwd)
    sources = _readable_sources(registry, source, cwd, outside_scope=outside_scope)
    if len(sources) >= MULTI_SOURCE_MIN and (ref is not None or worktree is not None):
        argument = "ref" if ref is not None else "worktree"
        raise InvalidArgumentError(
            message="引数が正しくありません: 1 件",
            violations=[
                Violation(
                    path=argument,
                    rule=f"{argument} は 1 つの Git の配信元を指すときだけ指定できます",
                )
            ],
        )
    current = current_source(registry.served(), path)
    targets: list[Target] = []
    for item, outside in sources:
        access = "read" if outside else access_of(item, path)
        if access is None:
            msg = "読む場所の権限が決まっていません"
            raise RuntimeError(msg)
        targets.append(_target_of(item, access, outside, ref, worktree, path, current))
    return targets


def _target_of(
    item: ServedSource,
    access: AccessLevel,
    outside: bool,
    ref: str | None,
    worktree: str | None,
    path: Path | None,
    current: tuple[ServedSource, Path | None] | None,
) -> Target:
    """1 つの配信元の読む場所を決める。"""
    if worktree is not None:
        wt = find_worktree(item, normalize_path(worktree))
        if wt is None:
            raise WorktreeNotMatchedError(
                message=f"{worktree} は {item.id} のワークツリーに該当しません",
                given=worktree,
                patterns=item.worktree_globs,
            )
        return Target(item, _base_of(item, wt), None, wt, access, outside_scope=outside)
    if ref is not None:
        if not item.is_git:
            raise InvalidArgumentError(
                message="引数が正しくありません: 1 件",
                violations=[
                    Violation(
                        path="ref",
                        rule="ref は 1 つの Git の配信元を指すときだけ指定できます",
                        fix=f"{item.id} は Git の管理外なので ref を省いてください",
                    )
                ],
            )
        return _revision_target(item, ref, access, outside)
    wt = find_worktree(item, path) if path is not None else None
    if wt is not None:
        return Target(item, _base_of(item, wt), None, wt, access, outside_scope=outside)
    if (current is not None and current[0].id == item.id) or not item.is_git:
        return Target(item, item.root, None, None, access, outside_scope=outside)
    return _revision_target(item, item.config.default_ref, access, outside)


def _revision_target(item: ServedSource, ref: str, access: AccessLevel, outside: bool) -> Target:
    """`ref` を commit へ 1 回だけ解き、その commit を持たせた読む場所を作る。"""
    repo_root = item.repo_root or item.root
    commit = resolve_ref(repo_root, ref, date_base=item.config.default_ref).commit
    return Target(item, item.root, ref, None, access, outside_scope=outside, commit=commit)


def resolve_write_target(
    *,
    registry: SourceRegistry,
    source: str | None = None,
    worktree: str | None = None,
    cwd: str | None = None,
) -> Target:
    """MCP の `source`・`worktree`・`cwd` から、書き込む場所を解く。"""
    path = _normalize(cwd)
    if source is None:
        current = current_source(registry.served(), path)
        if current is None:
            raise SourceNotWritableError(
                message=f"この作業場所（{cwd}）に作業中の配信元がありません",
                available=available_sources(cwd, registry=registry),
                next_steps=[DESCRIBE_HINT],
            )
        item = current[0]
    else:
        item = registry.get(source)
    if access_of(item, path) != "write":
        raise SourceNotWritableError(
            message=f"{item.id} にはこの作業場所（{cwd}）から書き込めません",
            available=available_sources(cwd, registry=registry),
            next_steps=[DESCRIBE_HINT],
        )
    if worktree is not None:
        wt = find_worktree(item, normalize_path(worktree))
        if wt is None:
            raise WorktreeNotMatchedError(
                message=f"{worktree} は {item.id} のワークツリーに該当しません",
                given=worktree,
                patterns=item.worktree_globs,
            )
    else:
        wt = find_worktree(item, path) if path is not None else None
    # Git の配信元はワークツリーにだけ書く
    if wt is None and item.is_git:
        # 設定をワークツリーから読む配信元でも、ワークツリーの親のクローン本体を返す
        clone = item.main_root or item.repo_root or item.root
        raise TargetIsCloneError(
            message=f"{clone} はクローン本体です。worktree でワークツリーを指してください",
            clone=str(clone),
            next_steps=["worktree 引数にワークツリーのパスを指定してください"],
        )
    # ワークツリーへ書くか
    if wt is not None:
        # 書く: 種類・置き場所をそのワークツリーの設定で参照するため、配信元を読み直す
        item = load_source_at(item, wt)
    return Target(item, _base_of(item, wt), None, wt, "write")

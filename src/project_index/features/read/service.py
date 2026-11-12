"""読み取り API の配信元の設定・文書の一覧・文書の取得・検討事項の取得。"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, cast

from project_index.features.convert.decisions import DECISION_DOCS_DIR, DECISION_ID
from project_index.features.read.paths import find_page
from project_index.features.read.types import (
    ConversionError,
    DecisionItem,
    DecisionResponse,
    DocumentListItem,
    DocumentListResponse,
    DocumentValueResponse,
    GitHubTarget,
    SourceConfigResponse,
)
from project_index.shared.errors import DecisionNotFoundError, DocumentNotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from project_index.features.access.types import Target
    from project_index.features.convert.service import ConvertService
    from project_index.features.documents.store import DocumentStore
    from project_index.features.documents.types import Document, LoadProblem
    from project_index.features.sources.types import DocumentTable, ServedSource


def _row_dict(row: DocumentTable) -> dict[str, Any]:
    """`documents[]` の 1 行を、配信元の設定のキー（`schema_path` は `schema`）の辞書にする。"""
    data = dataclasses.asdict(row)
    data["schema"] = data.pop("schema_path")
    return data


def get_source_config(source: ServedSource) -> SourceConfigResponse:
    """配信元の設定のうち、`nav`・`documents[]`・`decisions.folders`・`github` を返す。"""
    config = source.config
    github = (
        GitHubTarget(
            repository=config.github_repository, issue_labels=list(config.github_issue_labels)
        )
        if config.github_repository
        else None
    )
    return SourceConfigResponse(
        nav=config.nav,
        documents=[_row_dict(row) for row in config.documents],
        decisions={"folders": list(config.decision_folders)},
        github=github,
    )


def _tag_names(tags: object) -> list[str]:
    """メタデータの `tags` を文字列の並びにする（並びでなければ空）。"""
    if not isinstance(tags, list):
        return []
    return [str(tag) for tag in cast("list[object]", tags)]


def _metadata(document: Document) -> DocumentListItem:
    """文書の ID・パス・種類・共通のメタデータを一覧の 1 件にする。"""
    metadata = document.metadata
    return DocumentListItem(
        id=document.id,
        path=document.path,
        kind=document.kind,
        name=str(metadata.get("name") or document.id),
        description=metadata.get("description"),
        tags=_tag_names(metadata.get("tags")),
        visibility=metadata.get("visibility"),
        body_path=document.body_path,
    )


def _ref_name(target: Target) -> str:
    """応答の `ref` に出すリビジョンの名前を返す（Git 管理外の配信元は空）。"""
    source = target.source
    if not source.is_git:
        return ""
    return target.ref or source.config.default_ref


def list_documents(target: Target, *, store: DocumentStore) -> DocumentListResponse:
    """読み取りの場所の文書の ID・パス・種類・メタデータを、`documents[]` の行の順に返す。"""
    loaded = store.load(target)
    order = {row.id: index for index, row in enumerate(target.source.config.documents)}
    documents = sorted(
        loaded.documents, key=lambda found: (order.get(found.kind, len(order)), found.path)
    )
    return DocumentListResponse(
        ref=_ref_name(target), documents=[_metadata(found) for found in documents]
    )


def _unreadable(problems: Sequence[LoadProblem], path: str) -> LoadProblem | None:
    """パス（拡張子を落とした形も含む）が `path` と同じ、YAML を読めなかったファイルを探す。"""
    return next(
        (
            problem
            for problem in problems
            if problem.reason == "unreadable"
            and path in (problem.path, PurePosixPath(problem.path).with_suffix("").as_posix())
        ),
        None,
    )


def _kind_of(source: ServedSource, file: str) -> str:
    """ファイルのパスが当たる文書の行の ID を返す（当たる行が無ければ空）。"""
    for row in source.config.documents:
        if row.matches(file):
            return row.id
    return ""


def _file_time(file: Path) -> datetime:
    """ファイルの更新日時を返す。"""
    return datetime.fromtimestamp(file.stat().st_mtime, tz=UTC)


def get_document(
    target: Target, path: str, *, store: DocumentStore, converter: ConvertService
) -> DocumentValueResponse:
    """パスの文書の値・種類のスキーマ・メタデータを返し、`converters[]` を指す種類だけ変換する。"""
    source = target.source
    loaded = store.load(target)
    document = find_page(loaded.documents, path)
    # 文書が無い: YAML を読めなかったファイルなら読めなかった位置を返し、それも無ければ 404
    if document is None:
        broken = _unreadable(loaded.problems, path)
        if broken is None:
            raise DocumentNotFoundError(message=f"文書がありません: {path}", missing=[path])
        return DocumentValueResponse(
            source=source.id,
            ref=_ref_name(target),
            path=broken.path,
            value=None,
            schema=None,
            metadata=None,
            conversion_error=ConversionError(
                reason="invalid_yaml",
                kind=_kind_of(source, broken.path),
                detail=broken.detail,
                file=broken.path,
                line=broken.line,
                column=broken.column,
            ),
            updated_at=_file_time(source.root / broken.path),
        )
    # 種類が converters[] を指すときだけ、スクリプトの Markdown か変換の失敗を入れる
    markdown: str | None = None
    failure: ConversionError | None = None
    if source.table(document.kind).converter is not None:
        converted = converter.convert(target, document)
        if converted.failure is not None:
            failure = ConversionError.model_validate(dataclasses.asdict(converted.failure))
        else:
            markdown = converted.markdown
    is_row = document.body_path is not None
    return DocumentValueResponse(
        source=source.id,
        ref=_ref_name(target),
        path=document.path,
        value=document.data,
        schema=store.row_schema(target, document.kind),
        metadata=_metadata(document),
        body=document.body if is_row else None,
        body_path=document.body_path,
        markdown=markdown,
        conversion_error=failure,
        updated_at=document.updated or _file_time(source.root / document.path),
    )


def _decision_files(source: ServedSource) -> dict[str, list[tuple[str, Path]]]:
    """`decisions.folders` ごとに、検討事項の ID と文書のパスを集める。"""
    # 相対パスはメインのリポジトリの直下から数える（find_decisions と同じ）
    base = source.main_root or source.repo_root or source.root
    found: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    for folder in source.config.decision_folders:
        docs = (base / folder) / DECISION_DOCS_DIR
        # 無いフォルダは検討事項を持たないものとして飛ばす
        if not docs.is_dir():
            continue
        for file in sorted(docs.glob("*.md")):
            if file.is_file() and DECISION_ID.fullmatch(file.stem):
                found[file.stem].append((folder, file))
    return found


def list_decisions(source: ServedSource) -> list[DecisionItem]:
    """`decisions.folders` にある検討事項の ID と、ID ごとに当たるフォルダの数を返す。"""
    return [
        DecisionItem(id=decision, folders=len(files))
        for decision, files in sorted(_decision_files(source).items())
    ]


def get_decision(source: ServedSource, decision_id: str) -> DecisionResponse:
    """`decisions.folders` のうちちょうど 1 つのフォルダにある検討事項の文書の本文を返す。"""
    # 形式に当たらない ID は、フォルダの外を指さないようにファイルを読まずに断る
    if not DECISION_ID.fullmatch(decision_id):
        raise DecisionNotFoundError(
            message=f"{decision_id}: 検討事項の文書がありません", reason="not_found"
        )
    files = _decision_files(source).get(decision_id, [])
    # 0 個: 無い
    if not files:
        raise DecisionNotFoundError(
            message=f"{decision_id}: 検討事項の文書がありません", reason="not_found"
        )
    # 2 個以上: どのフォルダの文書か決まらない
    if len(files) > 1:
        raise DecisionNotFoundError(
            message=f"{decision_id}: 検討事項の文書が 1 つに決まりません",
            reason="ambiguous",
            folders=[folder for folder, _ in files],
        )
    folder, file = files[0]
    return DecisionResponse(id=decision_id, folder=folder, body=file.read_text(encoding="utf-8"))

"""書き込んだパスごとの、管理用の YAML の範囲と行の有無の判定と、通知の文面の作成。"""

from __future__ import annotations

import logging
import posixpath
from pathlib import Path
from typing import TYPE_CHECKING

from project_index.features.access.service import base_of, find_worktree
from project_index.features.documents.loader import collect_files, unindexed_files
from project_index.features.post_write.types import (
    NOTICE_PROMPT_ID,
    RULE_INDEX_FILE,
    Notice,
    PostWriteRequest,
    PostWriteResponse,
)
from project_index.features.seen.types import SessionKey
from project_index.integrations.git import ignored_paths
from project_index.shared.narrowing import is_dict, is_list
from project_index.shared.yaml_io import load_yaml

if TYPE_CHECKING:
    from collections.abc import Sequence

    from project_index.features.post_write.notified import NotifiedStore
    from project_index.features.prompt_doc.runtime import PromptSet
    from project_index.features.sources.types import DocumentTable, ServedSource

logger = logging.getLogger(__name__)


def judge_post_write(
    request: PostWriteRequest,
    *,
    sources: Sequence[ServedSource],
    notified: NotifiedStore,
    prompts: PromptSet,
) -> PostWriteResponse:
    """パスごとに通知の対象かを判定し、未通知のファイルの通知と文面を返す。"""
    # 通知の対象のパスの判定を集める（対象外のパスは記録しない）
    judged = [
        notice
        for path in request.paths
        if (notice := classify_path(Path(path), sources)) is not None
    ]
    # 同じ会話で通知済みのパスを除く
    key = SessionKey(request.session_id, request.agent_id or "")
    fresh = set(notified.take_new(key, [notice.path for notice in judged]))
    notices = [notice for notice in judged if notice.path in fresh]
    if not notices:
        return PostWriteResponse(notices=[], additional_context="")
    # 残った判定の配信元ごとに、エイリアスの行とルールの索引の有無を求める
    aliases, rule_index = _source_lines(notices, sources)
    text = prompts.render(
        NOTICE_PROMPT_ID,
        {
            "notices": [notice.model_dump() for notice in notices],
            "aliases": aliases,
            "rule_index": rule_index,
        },
    )
    logger.info("書き込みの後の通知を返した（%s・%s 件）", request.session_id, len(notices))
    return PostWriteResponse(notices=notices, additional_context=text)


def classify_path(path: Path, sources: Sequence[ServedSource]) -> Notice | None:
    """1 つのパスが通知の対象なら、配信元・促す修正・管理用の YAML を返す。"""
    located = _locate(path, sources)
    if located is None:
        return None
    source, base, relative = located
    # 配信元の設定と管理用の YAML そのものは通知しない
    index_tables = [
        table
        for table in source.config.documents
        if table.enabled and table.records is not None and table.body_file is not None
    ]
    index_paths = {table.id: collect_files(base, table) for table in index_tables}
    if relative in _config_paths(source) or any(
        relative in paths for paths in index_paths.values()
    ):
        return None
    found = _range_of(source, base, relative, index_tables, index_paths)
    # どの範囲にも入らない（YAML の文書・documents[].paths に該当しないファイル）
    if found is None:
        return None
    table, index_path = found
    # 範囲に入った管理用の YAML: 行の有無で促す修正を分ける
    has_row = _has_row(base, index_path, table, relative)
    return Notice(
        path=str(path),
        source=source.id,
        action="update_row" if has_row else "add_row",
        files_yaml=index_path,
    )


def _range_of(
    source: ServedSource,
    base: Path,
    relative: str,
    index_tables: Sequence[DocumentTable],
    index_paths: dict[str, list[str]],
) -> tuple[DocumentTable, str] | None:
    """相対パスを範囲に持つ管理用の YAML を、深いフォルダから順に探して返す。"""
    # Git の配信元だけ、Git が無視するパスを範囲から除く
    ignored = (ignored_paths(base) or []) if source.is_git else []
    index_dirs = {
        posixpath.dirname(item) or "." for paths in index_paths.values() for item in paths
    }
    for table, index_path in _candidates(relative, index_tables, index_paths):
        start = posixpath.dirname(index_path) or "."
        in_range = unindexed_files(
            base,
            index_path,
            (),
            table,
            files=[relative],
            others=[
                other for other in source.config.documents if other.enabled and other.id != table.id
            ],
            nested_dirs=_deeper_dirs(start, index_dirs),
            ignored=ignored,
        )
        if in_range:
            return table, index_path
    return None


def _source_lines(
    notices: Sequence[Notice], sources: Sequence[ServedSource]
) -> tuple[list[str], list[str]]:
    """通知の配信元のうち、alias_type の行を持つものと、直下に rules.yaml を持つものの ID を返す。"""
    by_id = {source.id: source for source in sources}
    source_ids = list(dict.fromkeys(notice.source for notice in notices))
    aliases = [
        source_id
        for source_id in source_ids
        if any(table.enabled and table.alias_type for table in by_id[source_id].config.documents)
    ]
    rule_index = [
        source_id for source_id in source_ids if (by_id[source_id].root / RULE_INDEX_FILE).is_file()
    ]
    return aliases, rule_index


def _locate(path: Path, sources: Sequence[ServedSource]) -> tuple[ServedSource, Path, str] | None:
    """パスを含む最初の配信元と、文書の相対パスを解くフォルダと、そこからの相対パスを返す。"""
    for source in sources:
        # ワークツリーの中なら、リポジトリからの相対位置をつないだフォルダから解く
        base = base_of(source, find_worktree(source, path))
        if path.is_relative_to(base):
            return source, base, path.relative_to(base).as_posix()
    return None


def _config_paths(source: ServedSource) -> set[str]:
    """配信元の設定ファイルの、配信元のフォルダからのパスを返す（ワークツリーでも同じパス）。"""
    # 配信元のフォルダの外部にある設定ファイルは、範囲のファイルにならない
    return {
        config_file.relative_to(source.root).as_posix()
        for config_file in source.config_files
        if config_file.is_relative_to(source.root)
    }


def _candidates(
    relative: str,
    tables: Sequence[DocumentTable],
    index_paths: dict[str, list[str]],
) -> list[tuple[DocumentTable, str]]:
    """相対パスを配下に持つ管理用の YAML を、深いフォルダから順に並べる。"""
    found: list[tuple[DocumentTable, str]] = []
    for table in tables:
        for index_path in index_paths[table.id]:
            start = posixpath.dirname(index_path)
            # 配信元の直下の管理用の YAML は全てのパスを配下に持つ
            if not start or relative.startswith(f"{start}/"):
                found.append((table, index_path))
    return sorted(found, key=lambda item: item[1].count("/"), reverse=True)


def _deeper_dirs(start: str, index_dirs: set[str]) -> list[str]:
    """`start` より深いフォルダにある管理用の YAML のフォルダを返す。"""
    # 配信元の直下の管理用の YAML: 直下でない全てのフォルダが深い
    if start == ".":
        return [folder for folder in index_dirs if folder != "."]
    return [folder for folder in index_dirs if folder.startswith(f"{start}/")]


def _has_row(base: Path, index_path: str, table: DocumentTable, relative: str) -> bool:
    """管理用の YAML の要素に、相対パスのファイルを指す行があるか。"""
    data = load_yaml((base / index_path).read_text(encoding="utf-8"))
    if not is_dict(data) or table.records is None or table.body_file is None:
        return False
    records = data.get(table.records)
    if not is_list(records):
        return False
    # 要素のパスは管理用の YAML のフォルダからのパス
    start = posixpath.dirname(index_path)
    expected = posixpath.relpath(relative, start) if start else relative
    return any(is_dict(record) and record.get(table.body_file) == expected for record in records)

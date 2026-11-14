"""新しい文書の配置先。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from project_index.shared.errors import InvalidArgumentError, Violation

if TYPE_CHECKING:
    from project_index.features.sources.types import DocumentTable

GLOB_CHARS = re.compile(r"[*?\[]")
RECURSIVE = "**/"


def _undecided(table: DocumentTable) -> InvalidArgumentError:
    """配置先を決められないエラーを作る（添字は書き込みが付ける）。"""
    return InvalidArgumentError(
        message=f"{table.id} の新しい文書の配置先を決められません",
        violations=[
            Violation(
                path="kind",
                rule=f"{table.id} の新しい文書の配置先を決められません",
                fix="documents[].paths の先頭を glob にしてください",
            )
        ],
    )


def _excluded(table: DocumentTable, path: str) -> InvalidArgumentError:
    """配置先が除外の名前に当たるエラーを作る（添字は書き込みが付ける）。"""
    rule = f"配置先 {path} が {table.id} の exclude に該当します"
    return InvalidArgumentError(
        message=rule,
        violations=[
            Violation(
                path="kind",
                rule=rule,
                fix="id を変えるか、documents[].exclude から削除してください",
            )
        ],
    )


def new_document_path(table: DocumentTable, doc_id: str) -> tuple[str, bool]:
    """`create` の文書を書くファイルを、文書の行の `paths` の先頭から決める。"""
    first = table.paths[0] if table.paths else ""
    has_glob = bool(GLOB_CHARS.search(first))
    if table.records is not None:
        if has_glob or not first:
            raise _undecided(table)
        # 管理用の YAML の名前が除外の名前に当たると、要素を足しても文書にならない
        if table.excludes(first):
            raise _excluded(table, first)
        return first, True
    if not has_glob:
        raise _undecided(table)
    folder, _, name = first.rpartition("/")
    folder = folder.replace(RECURSIVE, "").removesuffix("/**")
    # 最後の段の `*` を ID に置き換える
    filename = name.replace("*", doc_id, 1)
    if GLOB_CHARS.search(filename):
        raise _undecided(table)
    folder = "/".join(part for part in folder.split("/") if not GLOB_CHARS.search(part))
    path = f"{folder}/{filename}" if folder else filename
    # 配置先のファイル名が除外の名前に当たると、書いても文書にならない
    if table.excludes(path):
        raise _excluded(table, path)
    return path, False

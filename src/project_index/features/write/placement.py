"""新しい文書の配置先。"""

from __future__ import annotations

import posixpath
import re
from typing import TYPE_CHECKING

from project_index.shared.errors import InvalidArgumentError, Violation

if TYPE_CHECKING:
    from project_index.features.sources.types import DocumentTable

GLOB_CHARS = re.compile(r"[*?\[]")
RECURSIVE = "**/"


# 配置先を決められないときの修正案
FIX_RECORDS_SINGLE_FILE = "documents[].paths の先頭を glob を含まない 1 つのファイルにしてください"
FIX_NEEDS_GLOB = "documents[].paths の先頭を glob にしてください"
FIX_FILENAME_SINGLE_STAR = (
    "documents[].paths の先頭のファイル名の glob を * の 1 つだけにしてください"
)
FIX_FOLDER_RECURSIVE = "documents[].paths の先頭のフォルダの階層の glob を ** にしてください"


def _undecided(table: DocumentTable, fix: str) -> InvalidArgumentError:
    """配置先を決められないエラーを、決められない理由に合う修正案で作る（添字は書き込みが付ける）。"""
    return InvalidArgumentError(
        message=f"{table.id} の新しい文書の配置先を決められません",
        violations=[
            Violation(
                path="kind",
                rule=f"{table.id} の新しい文書の配置先を決められません",
                fix=fix,
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
            # 要素を追加する 1 つのファイルを先頭に指定させる
            raise _undecided(table, FIX_RECORDS_SINGLE_FILE)
        # 管理用の YAML の名前が除外の名前に当たると、要素を足しても文書にならない
        if table.excludes(first):
            raise _excluded(table, first)
        return first, True
    if not has_glob:
        # ID から 1 ファイルを作る glob を先頭に指定させる
        raise _undecided(table, FIX_NEEDS_GLOB)
    folder, _, name = first.rpartition("/")
    folder = folder.replace(RECURSIVE, "").removesuffix("/**")
    # 最後の段の `*` を ID に置き換える
    filename = name.replace("*", doc_id, 1)
    if GLOB_CHARS.search(filename):
        # ID に置き換えた後も glob が残る: ファイル名の glob を `*` 1 つに絞らせる
        raise _undecided(table, FIX_FILENAME_SINGLE_STAR)
    folder = "/".join(part for part in folder.split("/") if not GLOB_CHARS.search(part))
    path = f"{folder}/{filename}" if folder else filename
    # 配置先のファイル名が除外の名前に当たると、書いても文書にならない
    if table.excludes(path):
        raise _excluded(table, path)
    # `**` 以外の glob を含むフォルダの階層を取り除いた配置先は、`paths` に当たらず書いても文書にならない
    if not table.matches(path):
        # フォルダの階層の glob を `**` にさせる（`**` の階層は取り除いても `paths` に当たる）
        raise _undecided(table, FIX_FOLDER_RECURSIVE)
    return path, False


def _requested_invalid(rule: str, fix: str) -> InvalidArgumentError:
    """`create`・`rename` の `new_path` の違反を作る（添字は書き込みが付ける）。"""
    return InvalidArgumentError(
        message=rule, violations=[Violation(path="new_path", rule=rule, fix=fix)]
    )


def normalized_new_path(new_path: str) -> str:
    """`create`・`rename` の `new_path` を正規化し、配信元の外を指すパスを断る。"""
    path = posixpath.normpath(new_path)
    # 絶対パスか、正規化しても `..` が残る: 配信元の直下より上を指す
    if posixpath.isabs(path) or ".." in path.split("/"):
        rule = f"new_path（{new_path}）が配信元の外を指します"
        raise _requested_invalid(rule, "配信元の直下からのパスを指定してください")
    return path


def requested_document_path(table: DocumentTable, new_path: str) -> str:
    """`create` の `new_path` を正規化し、文書の行の文書になるパスかを確認して配置先にする。"""
    if table.records is not None:
        # 要素を追加する管理用の YAML は `paths` の先頭で決まるため、パスを受けない
        rule = f"{table.id} は records を持つため create の new_path を受けません"
        raise _requested_invalid(rule, "new_path を除いてください")
    # `**` で始まる `paths` は配信元の外を指すパスにも当たるため、照合より先に断る
    path = normalized_new_path(new_path)
    if not table.matches(path):
        # `paths` に当たらないか `exclude` に当たる: 書いても文書にならない
        rule = f"new_path（{path}）が {table.id} の paths に該当しないか exclude に該当します"
        fix = f"{table.id} の documents[].paths に該当するパスを指定してください"
        raise _requested_invalid(rule, fix)
    return path

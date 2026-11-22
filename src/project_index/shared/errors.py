"""索引のサーバーのエラーの階層。"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Literal

from project_index.shared.narrowing import is_dict, is_list


@dataclass(frozen=True, slots=True, kw_only=True)
class Violation:
    """違反 1 件の項目のパス・決まり・直し方。"""

    path: str
    rule: str
    fix: str = ""
    index: int | None = None
    doc: str | None = None


@dataclass(kw_only=True)
class ProjectIndexError(Exception):
    """MCP の isError と読み取り API の problem+json に変換するエラーの基底。"""

    message: str = ""
    next_steps: list[str] = field(default_factory=list[str])
    status: ClassVar[int] = 500

    def __str__(self) -> str:
        return self.message

    @property
    def name(self) -> str:
        """クラスの名前（MCP の本文の先頭と problem+json の type の末尾に出す）。"""
        return type(self).__name__

    def details(self) -> dict[str, Any]:
        """子クラスが持つ追加のプロパティを辞書で返す。"""
        base = {item.name for item in dataclasses.fields(ProjectIndexError)}
        result: dict[str, Any] = {}
        for item in dataclasses.fields(self):
            if item.name in base:
                continue
            result[item.name] = _plain(getattr(self, item.name))
        return result


def _plain(value: object) -> object:
    """違反と権限の dataclass を辞書に、パスを文字列にし、配列と辞書は中身を再帰で直す。"""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if is_list(value):
        return [_plain(item) for item in value]
    if is_dict(value):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, Path):
        return str(value)
    return value


@dataclass(kw_only=True)
class UnknownSourceError(ProjectIndexError):
    """無い配信元。"""

    status: ClassVar[int] = 404
    source_id: str = ""


@dataclass(kw_only=True)
class SourceNotReadableError(ProjectIndexError):
    """読めない配信元。"""

    status: ClassVar[int] = 403
    available: list[Any] = field(default_factory=list[Any])


@dataclass(kw_only=True)
class SourceNotWritableError(ProjectIndexError):
    """書き込めない配信元。"""

    status: ClassVar[int] = 403
    available: list[Any] = field(default_factory=list[Any])


@dataclass(kw_only=True)
class SourceNotServedError(ProjectIndexError):
    """配信していない配信元。"""

    status: ClassVar[int] = 404
    violations: list[Violation] = field(default_factory=list[Violation])
    disabled: bool = False


@dataclass(kw_only=True)
class WorktreeNotMatchedError(ProjectIndexError):
    """ワークツリーに当たらない。"""

    status: ClassVar[int] = 400
    given: str = ""
    patterns: list[str] = field(default_factory=list[str])


@dataclass(kw_only=True)
class TargetIsCloneError(ProjectIndexError):
    """書く先がクローン本体。"""

    status: ClassVar[int] = 409
    clone: str = ""


@dataclass(kw_only=True)
class InvalidArgumentError(ProjectIndexError):
    """引数の誤り。"""

    status: ClassVar[int] = 400
    violations: list[Violation] = field(default_factory=list[Violation])


@dataclass(kw_only=True)
class NavInvalidError(ProjectIndexError):
    """画面の構成の違反。"""

    status: ClassVar[int] = 400
    violations: list[Violation] = field(default_factory=list[Violation])


@dataclass(kw_only=True)
class RefNotFoundError(ProjectIndexError):
    """無いリビジョン。"""

    status: ClassVar[int] = 404
    argument: str = ""
    value: str = ""


@dataclass(kw_only=True)
class UnknownKindError(ProjectIndexError):
    """知らない種類。"""

    status: ClassVar[int] = 400
    kinds: list[str] = field(default_factory=list[str])


@dataclass(kw_only=True)
class DocumentNotFoundError(ProjectIndexError):
    """無い文書。"""

    status: ClassVar[int] = 404
    missing: list[str] = field(default_factory=list[str])
    candidates: dict[str, list[str]] = field(default_factory=dict[str, list[str]])


@dataclass(kw_only=True)
class ValidationFailedError(ProjectIndexError):
    """検査の不合格。"""

    status: ClassVar[int] = 422
    violations: list[Violation] = field(default_factory=list[Violation])


@dataclass(kw_only=True)
class VersionMismatchError(ProjectIndexError):
    """バージョンの不一致。"""

    status: ClassVar[int] = 409
    doc_id: str = ""
    current: str = ""
    diff: str = ""


@dataclass(kw_only=True)
class DocumentReferencedError(ProjectIndexError):
    """参照されている。"""

    status: ClassVar[int] = 409
    doc_id: str = ""
    referrers: list[str] = field(default_factory=list[str])


@dataclass(kw_only=True)
class DeleteNotAllowedError(ProjectIndexError):
    """削除を許していない種類。"""

    status: ClassVar[int] = 403
    kind: str = ""


@dataclass(kw_only=True)
class ReadOnlyKindError(ProjectIndexError):
    """SQLite の表の行の種類への操作（読み取り専用）。"""

    status: ClassVar[int] = 403
    kind: str = ""
    # 断った操作の位置（`operations[{番号}]`・`targets[{番号}]`・`writes[{番号}]`・`deletes[{番号}]`）
    positions: list[str] = field(default_factory=list[str])

    @property
    def violations(self) -> list[Violation]:
        """断った操作の位置ごとの違反（problem+json の `errors[]` にする）。"""
        return [
            Violation(
                path=position,
                rule=f"{self.kind} は SQLite の表の行の種類で、読み取り専用です",
                fix="SQLite の表の行は、データを持つアプリで書き換えてください",
            )
            for position in self.positions
        ]


@dataclass(kw_only=True)
class LastReadNotFoundError(ProjectIndexError):
    """前回読んだ記録が無い。"""

    status: ClassVar[int] = 400


@dataclass(kw_only=True)
class CrossOriginError(ProjectIndexError):
    """別のオリジンからの要求。"""

    status: ClassVar[int] = 403


@dataclass(kw_only=True)
class ConfigNotFoundError(ProjectIndexError):
    """配信元の設定が無い。"""

    status: ClassVar[int] = 404
    path: str = ""


@dataclass(kw_only=True)
class ConfigParseError(ProjectIndexError):
    """配信元の設定が YAML として読めない。"""

    status: ClassVar[int] = 400
    line: int | None = None
    column: int | None = None


@dataclass(kw_only=True)
class ConvertScriptError(ProjectIndexError):
    """変換スクリプトの失敗。"""

    status: ClassVar[int] = 422
    script: str = ""


@dataclass(kw_only=True)
class ConverterNotDefinedError(ProjectIndexError):
    """種類が `converters[]` を指さない。"""

    status: ClassVar[int] = 400
    kind: str = ""


@dataclass(kw_only=True)
class DecisionNotFoundError(ProjectIndexError):
    """検討事項の文書が 1 つに決まらない。"""

    status: ClassVar[int] = 404
    reason: Literal["not_found", "ambiguous"] = "not_found"
    folders: list[str] = field(default_factory=list[str])


@dataclass(kw_only=True)
class RestartInProgressError(ProjectIndexError):
    """再起動か更新の途中。"""

    status: ClassVar[int] = 409


@dataclass(kw_only=True)
class UpdateFailedError(ProjectIndexError):
    """更新のコマンドの失敗。"""

    status: ClassVar[int] = 500
    command: list[str] = field(default_factory=list[str])
    stderr: str = ""


@dataclass(kw_only=True)
class WriteDeadlineExceededError(ProjectIndexError):
    """書き込みの期限の超過（ファイルを書き換えずに止めた）。"""

    status: ClassVar[int] = 504
    deadline_sec: float = 0
    elapsed_sec: float = 0


@dataclass(kw_only=True)
class WorktreeLoadingError(ProjectIndexError):
    """ワークツリーの読み込み中（読み込みは続けている）。"""

    status: ClassVar[int] = 503
    worktree: str = ""


@dataclass(kw_only=True)
class RevisionExportTimeoutError(ProjectIndexError):
    """リビジョンの書き出しの待ち時間の超過（書き出しを止めた）。"""

    status: ClassVar[int] = 504
    operation: str = "revision_export"
    commit: str = ""
    limit_sec: float = 0


@dataclass(kw_only=True)
class DirectCommitNotConfiguredError(ProjectIndexError):
    """直コミットを使用できない配信元。"""

    status: ClassVar[int] = 409
    source_id: str = ""
    reason: str = ""


@dataclass(kw_only=True)
class DirectCommitNotPermittedError(ProjectIndexError):
    """直コミットを呼べない作業場所。"""

    status: ClassVar[int] = 403
    source_id: str = ""
    kinds: list[str] = field(default_factory=list[str])


@dataclass(kw_only=True)
class BranchNotAllowedError(ProjectIndexError):
    """上書きできないブランチ。"""

    status: ClassVar[int] = 403
    branch: str = ""
    allowed: list[str] = field(default_factory=list[str])


@dataclass(kw_only=True)
class CommitWorktreeNotFoundError(ProjectIndexError):
    """コミットするブランチのワークツリーが無い。"""

    status: ClassVar[int] = 409
    branch: str = ""


@dataclass(kw_only=True)
class UnpushedCommitsError(ProjectIndexError):
    """ワークツリーの未プッシュのコミット。"""

    status: ClassVar[int] = 409
    worktree: str = ""
    ahead: int = 0
    behind: int = 0


@dataclass(kw_only=True)
class UncommittedChangesError(ProjectIndexError):
    """書き込むファイルの未コミットの変更。"""

    status: ClassVar[int] = 409
    paths: list[str] = field(default_factory=list[str])


@dataclass(kw_only=True)
class FetchFailedError(ProjectIndexError):
    """リモートからの取得の失敗。"""

    status: ClassVar[int] = 502
    stderr: str = ""


@dataclass(kw_only=True)
class PushRejectedError(ProjectIndexError):
    """リモートにプッシュを断られた。"""

    status: ClassVar[int] = 409
    reason: str = ""


@dataclass(kw_only=True)
class PushFailedError(ProjectIndexError):
    """プッシュの失敗・結果の不明。"""

    status: ClassVar[int] = 502
    stderr: str = ""
    # 届いたかを確かめられなかったか
    unknown: bool = False
    # 届いたか不明なときに、作ったコミットの SHA
    commit: str = ""


@dataclass(kw_only=True)
class DirectCommitGeneratorError(ProjectIndexError):
    """直コミットの生成の失敗。"""

    status: ClassVar[int] = 500
    script: str = ""
    reason: str = ""

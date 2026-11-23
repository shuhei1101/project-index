"""書き込みと削除の要求・結果の型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from project_index.features.access.types import CWD_DESCRIPTION
from project_index.features.search.types import Condition, Group
from project_index.features.validation.markdown import UncheckedKey
from project_index.shared.api_model import ApiModel
from project_index.shared.errors import Violation

if TYPE_CHECKING:
    from project_index.features.write.source_config import SourceConfigFile

OPERATIONS_MAX = 50


@dataclass(frozen=True, slots=True, kw_only=True)
class WriteViolation(Violation):
    """スキーマの説明を持てる書き込みの違反。"""

    # 違反した項目のスキーマの定義から取り出した説明（`title`・`description` など）
    schema: dict[str, Any] | None = None


class TextEdit(BaseModel):
    """文字列の項目の一部を置き換える操作。"""

    model_config = ConfigDict(extra="forbid")

    field: str
    old: str
    new: str
    replace_all: bool = False


class Operation(BaseModel):
    """`write_docs` の `operations` の 1 件。"""

    model_config = ConfigDict(extra="forbid")

    op: Literal["create", "update", "replace", "rename", "replace_text"]
    kind: str | None = None
    id: str | None = None
    expected_version: str | dict[str, str] | None = None
    data: dict[str, Any] | None = None
    set: dict[str, Any] = Field(default_factory=dict[str, Any])
    unset: list[str] = Field(default_factory=list[str])
    add_to: dict[str, list[Any]] = Field(default_factory=dict[str, list[Any]])
    remove_from: dict[str, list[Any]] = Field(default_factory=dict[str, list[Any]])
    text_edits: list[TextEdit] = Field(default_factory=list[TextEdit])
    new_id: str | None = None
    new_path: str | None = None
    filter: Condition | Group | None = None
    old: str | None = None
    new: str | None = None
    fields: list[str] | None = None


class CommitSpec(BaseModel):
    """`write_docs`・`delete_docs` の `commit`。"""

    model_config = ConfigDict(extra="forbid")

    message: str
    # `None` は配信元の設定の `direct_commit.branch`
    branch: str | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        """空白だけの説明を断る。"""
        if not value.strip():
            message = "コミットの説明が空です"
            raise ValueError(message)
        return value


@dataclass(frozen=True)
class CommitResult:
    """直コミットでプッシュしたコミット。"""

    sha: str
    branch: str
    # プッシュが 1 回断られ、取得からやり直したか
    retried: bool


class WriteRequest(BaseModel):
    """`write_docs` の引数。"""

    model_config = ConfigDict(extra="forbid")

    operations: list[Operation]
    source: str | None = None
    worktree: str | None = None
    atomic: bool = True
    dry_run: bool = False
    cwd: str | None = Field(default=None, description=CWD_DESCRIPTION)
    session_id: str | None = None
    agent_id: str | None = None
    # 直コミット。`None` はコミットとプッシュをしない
    commit: CommitSpec | None = None


@dataclass(frozen=True)
class ReferenceChange:
    """`rename` で書き換えた参照元の 1 か所。"""

    path: str
    before: str
    after: str


@dataclass(frozen=True)
class SkippedOperation:
    """違反にせず何もしなかった `unset` の要素・`remove_from` のキー 1 件。"""

    path: str
    reason: str


@dataclass(frozen=True)
class WriteResultItem:
    """操作 1 件の結果。"""

    index: int
    id: str | None
    status: Literal["created", "updated", "replaced", "renamed", "deleted", "failed"]
    version: str | None = None
    diff: str | None = None
    errors: list[Violation] = field(default_factory=list[Violation])
    unchecked: list[UncheckedKey] = field(default_factory=list[UncheckedKey])
    skipped: list[SkippedOperation] = field(default_factory=list[SkippedOperation])
    path: str | None = None
    renamed_from: str | None = None
    references: list[ReferenceChange] = field(default_factory=list[ReferenceChange])
    count: int | None = None


@dataclass(frozen=True)
class WriteResult:
    """`write_docs` が返すもの。"""

    applied: bool
    results: list[WriteResultItem]
    # `commit` を指定し `dry_run: false` で書き込んだときだけ
    commit: CommitResult | None = None


class DeleteTarget(BaseModel):
    """`delete_docs` の `targets` の 1 件。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    expected_version: str


class DeleteRequest(BaseModel):
    """`delete_docs` の引数。"""

    model_config = ConfigDict(extra="forbid")

    targets: list[DeleteTarget]
    source: str | None = None
    worktree: str | None = None
    on_referenced: Literal["fail", "unlink"] = "fail"
    atomic: bool = True
    dry_run: bool = False
    cwd: str | None = Field(default=None, description=CWD_DESCRIPTION)
    commit: CommitSpec | None = None


@dataclass(frozen=True)
class DeleteResult:
    """`delete_docs` が返すもの。"""

    applied: bool
    results: list[WriteResultItem]
    unlinked: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    commit: CommitResult | None = None


class SourceConfigWrite(ApiModel):
    """書き込みの API の `sourceConfig`（配信元の設定の書き換え）。"""

    model_config = ConfigDict(extra="forbid")

    # 書き換えた後の `project-index.yaml` の内容の全体
    content: str = Field(min_length=1)
    # 配信元の設定の原本の取得が返した `version`
    expected_version: str


@dataclass(frozen=True)
class SourceConfigResult:
    """配信元の設定の書き換えのバージョン・差分・再読み込み。"""

    version: str
    diff: str
    # プッシュした後に配信元を再読み込みしたとき `True`
    reloaded: bool


@dataclass(frozen=True)
class CommitDocumentsRequest:
    """書き込みの API がサービスに渡す要求。"""

    source: str
    commit: CommitSpec
    writes: list[Operation] = field(default_factory=list[Operation])
    deletes: list[DeleteTarget] = field(default_factory=list[DeleteTarget])
    on_referenced: Literal["fail", "unlink"] = "fail"
    dry_run: bool = False
    # 本文の `baseCommit`。`None` のときは衝突してもブランチに残さずに断る
    base_commit: str | None = None
    # 本文の `sourceConfig`。`None` は配信元の設定を書き換えない
    source_config: SourceConfigWrite | None = None


@dataclass(frozen=True)
class ScriptRunResult:
    """衝突したときのスクリプトの終了コードと出力。"""

    # 制限時間で止めたときと、コマンドを起動できなかったときは `None`
    exit_code: int | None
    timed_out: bool
    # 末尾 `SCRIPT_OUTPUT_TAIL_CHARS` 文字
    stdout: str
    # 末尾 `SCRIPT_OUTPUT_TAIL_CHARS` 文字。起動できなかったときはその理由
    stderr: str


@dataclass(frozen=True)
class ConflictResult:
    """衝突して残したブランチ・コミット・今のブランチで断った理由・スクリプトの結果。"""

    # 試しに書くときは `None`
    branch: str | None
    commit: str | None
    # `base_commit` を解いた 40 桁の SHA
    base_commit: str
    # 今のブランチで送出されたエラーを、problem+json の `errors[]` と同じ違反にしたもの
    errors: list[Violation]
    # `on_conflict` が無いか試しに書くときは `None`
    script: ScriptRunResult | None = None


@dataclass(frozen=True)
class CommitDocumentsResult:
    """書き込みと削除の直コミットが返すもの。"""

    applied: bool
    writes: list[WriteResultItem]
    deletes: list[WriteResultItem]
    unlinked: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    # `dry_run` のときは `None`
    commit: CommitResult | None = None
    # 衝突してブランチに残したとき（`dry_run` は残せるとき）だけ持つ
    conflict: ConflictResult | None = None
    # `source_config` を受けたときだけ持つ
    source_config: SourceConfigResult | None = None


class CommitDeleteTarget(ApiModel):
    """書き込みの API の本文の `deletes` の 1 件。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    expected_version: str


class CommitDocumentsBody(ApiModel):
    """`POST /sources/{source}/commits` の本文。"""

    model_config = ConfigDict(extra="forbid")

    # 操作のキーは `write_docs` の `operations[]` のまま
    writes: list[Operation] = Field(default_factory=list[Operation])
    deletes: list[CommitDeleteTarget] = Field(default_factory=list[CommitDeleteTarget])
    on_referenced: Literal["fail", "unlink"] = "fail"
    message: str
    branch: str | None = None
    dry_run: bool = False
    # 画面が編集を始めたときのコミットするブランチのコミット
    base_commit: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,40}$")
    # 配信元の設定の書き換え
    source_config: SourceConfigWrite | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> CommitDocumentsBody:
        """書き込みと削除が両方とも空で、配信元の設定の書き換えも無い要求を断る。"""
        if not self.writes and not self.deletes and self.source_config is None:
            message = "writes と deletes が両方とも空で、sourceConfig もありません"
            raise ValueError(message)
        return self

    def to_request(self, source: str) -> CommitDocumentsRequest:
        """パスの配信元と合わせて、サービスに渡す要求にする。"""
        return CommitDocumentsRequest(
            source=source,
            commit=CommitSpec(message=self.message, branch=self.branch),
            writes=list(self.writes),
            deletes=[
                DeleteTarget(id=item.id, expected_version=item.expected_version)
                for item in self.deletes
            ],
            on_referenced=self.on_referenced,
            dry_run=self.dry_run,
            base_commit=self.base_commit,
            source_config=self.source_config,
        )


class CommitDocumentsItem(ApiModel):
    """書き込みの API の応答の `results[]` の 1 件。"""

    kind: Literal["write", "delete"]
    index: int
    id: str | None
    status: str
    version: str | None = None
    diff: str | None = None


class UnlinkedDocument(ApiModel):
    """書き込みの API の応答の `unlinked[]` の 1 件。"""

    id: str
    version: str


class CommitSummary(ApiModel):
    """書き込みの API の応答の `commit`。"""

    sha: str
    branch: str
    retried: bool


class ConflictError(ApiModel):
    """書き込みの API の応答の `conflict.errors[]` の 1 件（problem+json の `errors[]` と同じ構造）。"""

    path: str
    reason: str
    fix: str | None = None


class ScriptSummary(ApiModel):
    """書き込みの API の応答の `conflict.script`。"""

    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str


class ConflictSummary(ApiModel):
    """書き込みの API の応答の `conflict`。"""

    branch: str | None
    commit: str | None
    base_commit: str
    errors: list[ConflictError]
    script: ScriptSummary | None

    @classmethod
    def from_domain(cls, conflict: ConflictResult) -> ConflictSummary:
        """衝突したときの結果を応答の `conflict` にする。"""
        script = conflict.script
        return cls(
            branch=conflict.branch,
            commit=conflict.commit,
            base_commit=conflict.base_commit,
            errors=[
                ConflictError(path=item.path, reason=item.rule, fix=item.fix or None)
                for item in conflict.errors
            ],
            script=None
            if script is None
            else ScriptSummary(
                exit_code=script.exit_code,
                timed_out=script.timed_out,
                stdout=script.stdout,
                stderr=script.stderr,
            ),
        )


class SourceConfigSummary(ApiModel):
    """書き込みの API の応答の `sourceConfig`。"""

    version: str
    diff: str
    reloaded: bool


class SourceConfigFileResponse(ApiModel):
    """`GET /sources/{source}/config/file` の応答。"""

    content: str
    version: str
    branch: str
    protected_keys: list[str]

    @classmethod
    def from_domain(cls, file: SourceConfigFile) -> SourceConfigFileResponse:
        """配信元の設定の原本を応答にする。"""
        return cls(
            content=file.content,
            version=file.version,
            branch=file.branch,
            protected_keys=list(file.protected_keys),
        )


class CommitDocumentsResponse(ApiModel):
    """`POST /sources/{source}/commits` の応答。"""

    applied: bool
    results: list[CommitDocumentsItem]
    unlinked: list[UnlinkedDocument]
    commit: CommitSummary | None
    # 衝突しなかったときは `None`
    conflict: ConflictSummary | None = None
    # 配信元の設定を送らなかったときは `None`
    source_config: SourceConfigSummary | None = None

    @classmethod
    def from_domain(cls, result: CommitDocumentsResult) -> CommitDocumentsResponse:
        """書き込みと削除の結果を、書き込みに続けて削除の順の `results[]` にする。"""
        items = [
            CommitDocumentsItem(
                kind="write",
                index=item.index,
                id=item.id,
                status=item.status,
                version=item.version,
                diff=item.diff,
            )
            for item in result.writes
        ] + [
            CommitDocumentsItem(
                kind="delete",
                index=item.index,
                id=item.id,
                status=item.status,
                version=item.version,
                diff=item.diff,
            )
            for item in result.deletes
        ]
        commit = (
            None
            if result.commit is None
            else CommitSummary(
                sha=result.commit.sha, branch=result.commit.branch, retried=result.commit.retried
            )
        )
        return cls(
            applied=result.applied,
            results=items,
            unlinked=[
                UnlinkedDocument(id=doc_id, version=version) for doc_id, version in result.unlinked
            ],
            commit=commit,
            conflict=None
            if result.conflict is None
            else ConflictSummary.from_domain(result.conflict),
            source_config=None
            if result.source_config is None
            else SourceConfigSummary(
                version=result.source_config.version,
                diff=result.source_config.diff,
                reloaded=result.source_config.reloaded,
            ),
        )

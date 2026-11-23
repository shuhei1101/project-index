"""書き込みの API が配信元の設定（project-index.yaml）を直コミットで書き換えるときの許可・原本・検査。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from project_index.features.sources.service import validate_source_config
from project_index.features.write.direct_commit import resolve_commit_plan
from project_index.features.write.types import CommitSpec, WriteViolation
from project_index.shared.errors import (
    SourceConfigNotPermittedError,
    SourceConfigSplitError,
    ValidationFailedError,
)
from project_index.shared.hashing import content_hash, value_hash
from project_index.shared.narrowing import is_dict
from project_index.shared.yaml_io import YamlLoadError, load_yaml

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from project_index.features.sources.schema_ref import SchemaRefLookup
    from project_index.features.sources.types import ServedSource
    from project_index.shared.errors import Violation

# 書き込みの API が書き換えを断るトップレベルのキー（コマンドと、許可・書き込む先を決めるキー）
PROTECTED_KEYS = ("validators", "converters", "generators", "direct_commit", "worktrees")
# 書き換える配信元の設定の、配信元のフォルダからの相対パス
SOURCE_CONFIG_FILE = "project-index.yaml"


@dataclass(frozen=True)
class SourceConfigFile:
    """書き換える前の project-index.yaml の内容とバージョン。"""

    # ファイルの内容のまま（コメントを含む）
    content: str
    version: str
    # 配信元の設定の direct_commit.branch
    branch: str
    protected_keys: list[str]


def check_source_config_permitted(source: ServedSource) -> None:
    """端末の設定と配信元の設定の両方で、配信元の設定の直コミットを許可しているかを確かめる。"""
    missing: list[Literal["write_api_config", "direct_commit.config"]] = []
    settings = source.config.direct_commit
    # 端末の設定の sources[].direct_commit.write_api_config が偽
    if not source.direct_commit_write_api_config:
        missing.append("write_api_config")
    # 配信元の設定の direct_commit が無いか direct_commit.config が偽
    if settings is None or not settings.config:
        missing.append("direct_commit.config")
    if missing:
        raise SourceConfigNotPermittedError(
            message=f"{source.id} は書き込みの API から配信元の設定を直コミットできません",
            source_id=source.id,
            missing=missing,
            next_steps=[
                "端末の設定の sources[].direct_commit.write_api_config と、"
                "配信元の設定の direct_commit.config を true にしてください"
            ],
        )


def source_config_relative_path(source: ServedSource) -> str:
    """書き換える project-index.yaml の配信元のフォルダからの相対パスを返す。"""
    files = list(source.config_files)
    expected = (source.root / SOURCE_CONFIG_FILE).resolve()
    # 配信元のフォルダの project-index.yaml 1 つだけを読んでいる
    if len(files) == 1 and files[0].resolve() == expected:
        return SOURCE_CONFIG_FILE
    # 複数のファイルを重ねるか、別の名前のファイル: 書き換えた結果が読む値と合わないので断る
    raise SourceConfigSplitError(
        message=(
            f"{source.id} は配信元の設定を複数のファイルに分けているため、"
            "書き込みの API では書き換えられません"
        ),
        source_id=source.id,
        files=[str(path) for path in files],
        next_steps=["配信元の設定は PR を経て変えてください"],
    )


def read_source_config_file(source: ServedSource) -> SourceConfigFile:
    """コミットするブランチのワークツリーの project-index.yaml を読んで返す。"""
    check_source_config_permitted(source)
    relative = source_config_relative_path(source)
    # コミットするブランチとワークツリーを求める（取得はしない）
    plan = resolve_commit_plan(source, CommitSpec(message="read source config"))
    content = (plan.base / relative).read_text(encoding="utf-8")
    return SourceConfigFile(
        content=content,
        version=content_hash(content),
        branch=plan.branch,
        protected_keys=list(PROTECTED_KEYS),
    )


def protected_key_violations(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> list[WriteViolation]:
    """書き換える前と後で PROTECTED_KEYS の値が違うキーを違反にする。"""
    # 無いキーは None として比べ、値のハッシュで比べてコメントと書き方の違いは無視する
    return [
        WriteViolation(
            path=f"sourceConfig.{key}",
            rule="protected_key",
            fix="このキーは PR を経て変えてください",
        )
        for key in PROTECTED_KEYS
        if value_hash(before.get(key)) != value_hash(after.get(key))
    ]


def _load_mapping(text: str) -> dict[str, Any] | None:
    """YAML のマップとして読む（読めないかマップでなければ None）。"""
    try:
        value = load_yaml(text)
    except YamlLoadError:
        return None
    return cast("dict[str, Any]", value) if is_dict(value) else None


def check_source_config_content(
    content: str,
    *,
    current: str,
    root: Path,
    lookup: SchemaRefLookup | None = None,
) -> dict[str, Any]:
    """書き換えた後の配信元の設定を、書き換えられないキー・スキーマ・起動の検証にかける。"""
    # 1. 書き換えた後の内容を読む。読めないかマップでなければ、ほかの検査をせずに断る
    after = _load_mapping(content)
    if after is None:
        raise ValidationFailedError(
            message="配信元の設定が検査に合格しません（1 件）",
            violations=[
                WriteViolation(
                    path="sourceConfig.content",
                    rule="YAML のマップとして読めません",
                    fix="project-index.yaml の内容の全体を YAML のマップで送ってください",
                )
            ],
        )
    before = _load_mapping(current) or {}
    # 2. 書き換えられないキーの違反
    violations: list[Violation] = [*protected_key_violations(before, after)]
    # 3. 起動と同じ検証（違反のパスの頭に sourceConfig. を付ける）
    violations.extend(
        WriteViolation(
            path=f"sourceConfig.{item.path}" if item.path else "sourceConfig",
            rule=item.rule,
            fix=item.fix,
            index=item.index,
            doc=item.doc,
        )
        for item in validate_source_config(after, root=root, lookup=lookup)
    )
    if violations:
        raise ValidationFailedError(
            message=f"配信元の設定が検査に合格しません（{len(violations)} 件）",
            violations=violations,
        )
    return after

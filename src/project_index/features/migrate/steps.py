"""パッケージに入れた移し替えの手順を読み、メモリの上の YAML に当てる。"""
# pyright: reportUnknownArgumentType=warning, reportUnknownMemberType=warning, reportUnknownVariableType=warning

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Any, Literal, cast

from ruamel.yaml.comments import CommentedMap

from project_index.features.migrate.types import (
    MIGRATIONS_DIR,
    STEPS_FILE,
    MigrationFailedError,
    MigrationStep,
)
from project_index.shared.yaml_io import YamlLoadError, load_yaml

OPERATIONS = ("rename", "add", "delete", "lift", "unwrap")
ARRAY_SUFFIX = "[]"
WILDCARD = "*"


def load_steps(
    kind: Literal["settings", "project-index"], *, mine: str, current: str
) -> list[MigrationStep]:
    """対象のバージョンより新しく読めるバージョン以下の手順を、古い順に読む。"""
    root = resources.files("project_index") / MIGRATIONS_DIR / kind
    if not root.is_dir():
        return []
    versions = sorted(
        int(entry.name)
        for entry in root.iterdir()
        if entry.name.isdecimal() and int(mine) < int(entry.name) <= int(current)
    )
    steps: list[MigrationStep] = []
    for number in versions:
        name = str(number)
        steps.extend(_read_version(root / name / STEPS_FILE, name))
    return steps


def _read_version(file: Any, version: str) -> list[MigrationStep]:  # noqa: ANN401
    """1 つのバージョンの `steps.yaml` を手順にする。"""
    label = f"{version}/{STEPS_FILE}"
    try:
        value = load_yaml(file.read_text(encoding="utf-8"), file=label)
    except (OSError, YamlLoadError) as error:
        msg = f"{label}: {error}"
        raise MigrationFailedError(msg) from error
    rows = value.get("steps") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        msg = f"{label}: steps の並びがありません"
        raise MigrationFailedError(msg)
    steps: list[MigrationStep] = []
    for row in rows:
        # 操作は選択肢の中だけ。改名と引き上げは新しいキーを持ち、引き上げは取り出すキーも持つ
        if not isinstance(row, dict) or row.get("op") not in OPERATIONS:
            msg = f"{label}: op は {'・'.join(OPERATIONS)} のどれかです"
            raise MigrationFailedError(msg)
        if row["op"] in ("rename", "lift") and not row.get("to"):
            msg = f"{label}: {row['op']} には to が要ります（{row.get('path')}）"
            raise MigrationFailedError(msg)
        if row["op"] == "lift" and not row.get("take"):
            msg = f"{label}: lift には take が要ります（{row.get('path')}）"
            raise MigrationFailedError(msg)
        steps.append(
            MigrationStep(
                version=version,
                op=row["op"],
                path=str(row.get("path", "")),
                description=str(row.get("description", "")),
                to=row.get("to"),
                value=row.get("value"),
                match=row.get("match"),
                take=row.get("take"),
            )
        )
    return steps


@dataclass(frozen=True)
class _Parent:
    """末尾のキーを持つ親の辞書と、その親の辞書を持つ辞書（`lift` が使う）。"""

    node: CommentedMap
    owner: CommentedMap | None = None
    owner_key: str | None = None


def _parents(data: CommentedMap, parts: list[str]) -> list[_Parent]:
    """キーのパスの末尾の手前までをたどり、末尾のキーを持つ親の辞書を集める。"""
    parents = [_Parent(data)]
    for part in parts:
        next_parents: list[_Parent] = []
        for parent in parents:
            # `{キー}[]` は配列の要素ごとにたどる
            key = part.removesuffix(ARRAY_SUFFIX)
            child = parent.node.get(key)
            if part.endswith(ARRAY_SUFFIX):
                if isinstance(child, list):
                    next_parents.extend(
                        _Parent(item) for item in child if isinstance(item, CommentedMap)
                    )
            elif isinstance(child, CommentedMap):
                next_parents.append(_Parent(child, parent.node, key))
        parents = next_parents
    return parents


def _rename(parent: CommentedMap, step: MigrationStep, key: str) -> None:
    """同じ位置・同じコメントでキーを改名する。"""
    to = cast("str", step.to)
    if to in parent:
        msg = f"{step.version}: {step.path} を {to} に改名できません（{to} があります）"
        raise MigrationFailedError(msg)
    position = list(parent).index(key)
    comment = parent.ca.items.pop(key, None)
    value = parent.pop(key)
    parent.insert(position, to, value)
    if comment is not None:
        parent.ca.items[to] = comment


def _matches(value: Any, step: MigrationStep) -> bool:  # noqa: ANN401
    """値が辞書で、`match` のキーと値を全て持つか（`match` が無ければ辞書なら当たる）。"""
    if not isinstance(value, Mapping):
        return False
    return all(key in value and value[key] == item for key, item in (step.match or {}).items())


def _lift(parent: _Parent, step: MigrationStep, key: str) -> None:
    """値の `take` を、親の辞書を持つ辞書の `to` に置き、キーを削除する。"""
    value = parent.node[key]
    take = cast("str", step.take)
    to = cast("str", step.to)
    if parent.owner is None or not _matches(value, step) or take not in value:
        return
    if to in parent.owner:
        msg = f"{step.version}: {step.path} を {to} に引き上げられません（{to} があります）"
        raise MigrationFailedError(msg)
    parent.owner[to] = value[take]
    del parent.node[key]
    # 親の辞書が空になったら、親の辞書も削除する
    if not parent.node and parent.owner_key is not None:
        del parent.owner[parent.owner_key]


def _unwrap(parent: CommentedMap, step: MigrationStep, key: str) -> None:
    """辞書の値を、`take` の値（無ければキー名）に置き換える。"""
    value = parent[key]
    if _matches(value, step):
        parent[key] = value.get(step.take, key) if step.take is not None else key


def _apply_key(parent: _Parent, step: MigrationStep, key: str) -> None:
    """親の辞書の 1 つのキーに操作を当てる。"""
    node = parent.node
    if step.op == "rename":
        if key in node:
            _rename(node, step, key)
    elif step.op == "add":
        if key not in node:
            node[key] = step.value
    elif step.op == "delete":
        if key in node and (step.value is None or node[key] == step.value):
            del node[key]
    elif key in node:
        if step.op == "lift":
            _lift(parent, step, key)
        else:
            _unwrap(node, step, key)


def apply_step(data: CommentedMap, step: MigrationStep) -> None:
    """メモリの上の YAML に 1 つの手順を当てる。"""
    *parents_path, key = step.path.split(".")
    for parent in _parents(data, parents_path):
        # 末尾が `*` なら親の辞書の全てのキーに当てる（キーが無い親では何もしない）
        keys = list(parent.node) if key == WILDCARD else [key]
        for name in keys:
            _apply_key(parent, step, name)

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from project_index.features.migrate.steps import apply_step, load_steps
from project_index.features.migrate.types import MigrationFailedError, MigrationStep
from project_index.shared.yaml_io import dump_roundtrip, load_roundtrip

if TYPE_CHECKING:
    from collections.abc import Callable


def _rename_step(version: str = "2") -> dict[str, Any]:
    """`steps.yaml` の改名の 1 行を返す。"""
    return {"op": "rename", "path": "a", "to": "b", "description": f"{version} で a を b にする"}


def _step(op: str, path: str, **overrides: Any) -> MigrationStep:
    """手順 1 つを作る。"""
    values: dict[str, Any] = {
        "version": "2",
        "op": op,
        "path": path,
        "to": None,
        "value": None,
        "description": "手順",
    }
    values.update(overrides)
    return MigrationStep(**values)


def test_load_steps(write_steps: Callable[..., None]) -> None:
    """範囲のバージョンの手順を古い順に読む（正常系）。"""
    # 準備
    for version in ("2", "3", "10"):
        write_steps("settings", version, [_rename_step(version)])
    # 実行
    result = load_steps("settings", mine="2", current="10")
    # 検証
    assert [step.version for step in result] == ["3", "10"]
    assert [step.op for step in result] == ["rename", "rename"]
    assert result[0].to == "b"


def test_load_steps_when_none(write_steps: Callable[..., None]) -> None:
    """当てる手順が無い（正常系）。"""
    # 準備
    write_steps("settings", "2", [_rename_step()])
    # 実行
    result = load_steps("settings", mine="1", current="1")
    # 検証
    assert result == []


def test_load_steps_when_invalid_op(write_steps: Callable[..., None]) -> None:
    """知らない操作（異常系）。"""
    # 準備
    write_steps("settings", "2", [{"op": "copy", "path": "a", "description": "複製する"}])
    # 実行・検証
    with pytest.raises(MigrationFailedError, match=r"2/steps\.yaml"):
        load_steps("settings", mine="1", current="2")


def test_apply_step_when_rename() -> None:
    """同じ位置で改名し、コメントを残す（正常系）。"""
    # 準備
    data = load_roundtrip(
        "sources:\n  - id: a\n    # 権限の範囲\n    scope: x\n  - id: b\n    scope: y\n"
    )
    step = _step("rename", "sources[].scope", to="access")
    # 実行
    apply_step(data, step)
    # 検証
    dumped = dump_roundtrip(data)
    assert [row["access"] for row in data["sources"]] == ["x", "y"]
    assert [list(row) for row in data["sources"]] == [["id", "access"], ["id", "access"]]
    assert "# 権限の範囲" in dumped


def test_apply_step_when_add() -> None:
    """無いキーだけを追加する（正常系）。"""
    # 準備
    without_key = load_roundtrip("name: a\n")
    with_key = load_roundtrip("name: b\nlog_level: debug\n")
    step = _step("add", "log_level", value="info")
    # 実行
    apply_step(without_key, step)
    apply_step(with_key, step)
    # 検証
    assert without_key["log_level"] == "info"
    assert with_key["log_level"] == "debug"


def test_apply_step_when_delete() -> None:
    """キーを削除する（正常系）。"""
    # 準備
    data = load_roundtrip("name: a\nlegacy: 1\n")
    # 実行
    apply_step(data, _step("delete", "legacy"))
    # 検証
    assert "legacy" not in data
    assert data["name"] == "a"


def test_apply_step_when_rename_conflict() -> None:
    """改名先が既にある（異常系）。"""
    # 準備
    data = load_roundtrip("a: 1\nb: 2\n")
    # 実行・検証
    with pytest.raises(MigrationFailedError):
        apply_step(data, _step("rename", "a", to="b"))


def test_apply_step_when_delete_value() -> None:
    """値が一致するときだけ削除する（正常系）。"""
    # 準備
    data = load_roundtrip("documents:\n  - id: a\n    type: yaml\n  - id: b\n    type: markdown\n")
    step = _step("delete", "documents[].type", value="yaml")
    # 実行
    apply_step(data, step)
    # 検証
    assert "type" not in data["documents"][0]
    assert data["documents"][1]["type"] == "markdown"


def test_apply_step_when_lift() -> None:
    """値を行へ引き上げる（正常系）。"""
    # 準備
    data = load_roundtrip(
        "documents:\n"
        "  - id: a\n"
        "    metadata:\n"
        "      alias_type: {type: custom, value: term}\n"
        "  - id: b\n"
        "    metadata:\n"
        "      name: {type: ref, field: title}\n"
        "      alias_type: {type: custom, value: term}\n"
    )
    step = _step(
        "lift",
        "documents[].metadata.alias_type",
        to="alias_type",
        match={"type": "custom"},
        take="value",
    )
    # 実行
    apply_step(data, step)
    # 検証
    rows = data["documents"]
    assert [row["alias_type"] for row in rows] == ["term", "term"]
    assert "metadata" not in rows[0]
    assert list(rows[1]["metadata"]) == ["name"]


def test_apply_step_when_unwrap() -> None:
    """辞書の値を列名にする（正常系）。"""
    # 準備
    data = load_roundtrip(
        "documents:\n"
        "  - id: a\n"
        "    metadata:\n"
        "      name: {type: ref, field: title}\n"
        "      summary: {type: ref}\n"
        "      tags: {type: custom, value: [a]}\n"
    )
    step = _step("unwrap", "documents[].metadata.*", match={"type": "ref"}, take="field")
    # 実行
    apply_step(data, step)
    # 検証
    metadata = data["documents"][0]["metadata"]
    assert metadata["name"] == "title"
    assert metadata["summary"] == "summary"
    assert metadata["tags"]["type"] == "custom"


def test_apply_step_when_lift_conflict() -> None:
    """引き上げ先が既にある（異常系）。"""
    # 準備
    data = load_roundtrip(
        "documents:\n"
        "  - id: a\n"
        "    alias_type: doc\n"
        "    metadata:\n"
        "      alias_type: {type: custom, value: term}\n"
    )
    step = _step(
        "lift",
        "documents[].metadata.alias_type",
        to="alias_type",
        match={"type": "custom"},
        take="value",
    )
    # 実行・検証
    with pytest.raises(MigrationFailedError):
        apply_step(data, step)

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# エージェントフローの最小のスキーマ（`$ref` で同じフォルダの common.schema.yaml を指す）
AGENT_FLOW_SCHEMA = """\
type: object
additionalProperties: false
required: [id, summary, steps]
properties:
  id:
    $ref: common.schema.yaml#/$defs/id
  type:
    enum: [flow, skill]
  title:
    type: string
  summary:
    type: string
  skill:
    type: object
    required: [path]
  steps:
    type: array
    items:
      type: object
      required: [name]
allOf:
  - if:
      properties:
        type:
          const: skill
      required: [type]
    then:
      required: [skill]
"""
COMMON_SCHEMA = """\
$defs:
  id:
    type: string
"""


def _source_config(schema: str | dict[str, str]) -> str:
    """`agent_flow` の行だけを持つ配信元の設定を返却する。"""
    row: dict[str, Any] = {
        "id": "agent_flow",
        "title": "エージェントフロー",
        "paths": ["docs/agent-flow/*.yaml"],
        "exclude": ["index.yaml"],
        "schema": schema,
    }
    value = {"version": "3", "name": "sample", "documents": [row]}
    return json.dumps(value, ensure_ascii=False)


@pytest.fixture
def write_source() -> Callable[..., Path]:
    """配信元の設定とスキーマを記載し、配信元の直下を返却する関数を返却する。"""

    def _write(root: Path, schema: str | dict[str, str] = "schemas/agent_flow.schema.yaml") -> Path:
        # 配信元の設定（配信元のフォルダが無ければ作る）
        root.mkdir(parents=True, exist_ok=True)
        (root / "project-index.yaml").write_text(_source_config(schema), encoding="utf-8")
        # 配信元の中のスキーマ（文字列のスキーマの行が指す）
        (root / "schemas").mkdir(parents=True, exist_ok=True)
        (root / "schemas/agent_flow.schema.yaml").write_text(AGENT_FLOW_SCHEMA, encoding="utf-8")
        (root / "schemas/common.schema.yaml").write_text(COMMON_SCHEMA, encoding="utf-8")
        return root

    return _write


@pytest.fixture
def write_flow() -> Callable[[Path, str, dict[str, Any]], Path]:
    """`docs/agent-flow/{name}.yaml` にエージェントフローを記載し、そのパスを返却する関数を返却する。"""

    def _write(root: Path, name: str, data: dict[str, Any]) -> Path:
        path = root / "docs" / "agent-flow" / f"{name}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def skill_flow() -> Callable[..., dict[str, Any]]:
    """`type: skill` のエージェントフローの中身を作る関数を返却する。"""

    def _make(flow_id: str, **overrides: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": flow_id,
            "type": "skill",
            "title": f"{flow_id} のスキル",
            "summary": f"{flow_id} を進める",
            "skill": {"path": f"skills/{flow_id}/SKILL.md"},
            "steps": [{"name": "進める", "body": "進める。"}],
        }
        data.update(overrides)
        return data

    return _make


@pytest.fixture
def flow_flow() -> Callable[..., dict[str, Any]]:
    """`type: flow` のエージェントフローの中身を作る関数を返却する。"""

    def _make(flow_id: str, **overrides: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": flow_id,
            "type": "flow",
            "summary": f"{flow_id} の共通の工程",
            "steps": [{"name": "取得する", "body": "取得する。"}],
        }
        data.update(overrides)
        return data

    return _make

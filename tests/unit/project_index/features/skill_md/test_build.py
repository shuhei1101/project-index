from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import pytest
from project_index.features.skill_md.build import (
    build_skill_files,
    check_replacement,
    load_agent_flows,
    render_skill_md,
    resolve_steps,
    write_changed,
)
from project_index.features.skill_md.types import AgentFlowFile, InvalidAgentFlowError, SkillFile

from project_index.shared.yaml_io import load_yaml

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

RENDERED_BODY = """\
<!-- docs/agent-flow/a.yaml から生成した。このファイルを修正せず、設計書を修正して再生成する -->

# a のスキル

## 引数

| 引数 | 説明 |
| --- | --- |
| `$target` | 対象。省くと今のフォルダ |

## 手順

### 準備する

対象があるときだけ行う。

準備する。

呼ぶもの:

- コマンド `echo {target}`
- ツール `Read` `{required: [file_path]}`

### 進める

進める。
"""


def _split(text: str) -> tuple[dict[str, Any], str]:
    """SKILL.md を frontmatter の辞書と本文に分ける。"""
    _, front, body = text.split("---\n", 2)
    return load_yaml(front), body.removeprefix("\n")


# load_agent_flows


def test_load_agent_flows(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
) -> None:
    """文字列のスキーマとエージェントフローを読む（正常系）。"""
    # 準備
    root = write_source(tmp_path)
    write_flow(root, "b", skill_flow("b"))
    write_flow(root, "a", skill_flow("a"))
    write_flow(root, "index", {"items": []})
    # 実行
    flows, schema = load_agent_flows(root)
    # 検証
    assert [flow.path for flow in flows] == ["docs/agent-flow/a.yaml", "docs/agent-flow/b.yaml"]
    assert "$ref" not in str(schema["properties"]["id"])


def test_load_agent_flows_when_schema_ref(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ほかの配信元を指すスキーマを commit から読む（正常系）。"""
    # 準備
    schemas = git_repo(
        {
            "project-index.yaml": "name: schemas\ndocuments: []\n",
            "agent_flow.schema.yaml": "type: object\nrequired: [id]\ntitle: v1\n",
        },
        name="schemas",
    )
    run_git(schemas, "tag", "v1")
    (schemas / "agent_flow.schema.yaml").write_text("broken: [", encoding="utf-8")
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        json.dumps(
            {
                "version": "1",
                "clone": str(tmp_path),
                "sources": [{"id": "schemas", "config": str(schemas / "project-index.yaml")}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJECT_INDEX_CONFIG", str(settings))
    root = write_source(
        tmp_path / "sample",
        schema={"source": "schemas", "path": "agent_flow.schema.yaml", "ref": "v1"},
    )
    write_flow(root, "a", skill_flow("a"))
    # 実行
    _, schema = load_agent_flows(root)
    # 検証
    assert schema["title"] == "v1"


def test_load_agent_flows_when_schema_unresolvable(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """参照先の配信元が端末の設定に無い（異常系）。"""
    # 準備
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        json.dumps({"version": "1", "clone": str(tmp_path), "sources": []}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJECT_INDEX_CONFIG", str(settings))
    root = write_source(
        tmp_path / "sample",
        schema={"source": "nothing", "path": "agent_flow.schema.yaml", "ref": "v1"},
    )
    write_flow(root, "a", skill_flow("a"))
    # 実行
    with pytest.raises(InvalidAgentFlowError) as caught:
        load_agent_flows(root)
    # 検証
    assert [problem.file for problem in caught.value.problems] == [
        "nothing:agent_flow.schema.yaml@v1"
    ]


def test_load_agent_flows_when_unreadable(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
) -> None:
    """読めないエージェントフローがある（異常系）。"""
    # 準備
    root = write_source(tmp_path)
    write_flow(root, "a", skill_flow("a"))
    (root / "docs/agent-flow/c.yaml").write_text('summary: "unterminated\n', encoding="utf-8")
    # 実行
    with pytest.raises(InvalidAgentFlowError) as caught:
        load_agent_flows(root)
    # 検証
    assert [problem.file for problem in caught.value.problems] == ["docs/agent-flow/c.yaml"]


def test_load_agent_flows_when_row_missing(tmp_path: Path) -> None:
    """agent_flow の行が無い（異常系）。"""
    # 準備
    (tmp_path / "project-index.yaml").write_text(
        'version: "3"\nname: sample\ndocuments: []\n', encoding="utf-8"
    )
    # 実行
    with pytest.raises(InvalidAgentFlowError) as caught:
        load_agent_flows(tmp_path)
    # 検証
    assert [problem.file for problem in caught.value.problems] == ["project-index.yaml"]


# build_skill_files


def test_build_skill_files(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
    flow_flow: Callable[..., dict[str, Any]],
) -> None:
    """type: skill だけを組み立てる（正常系）。"""
    # 準備
    root = write_source(tmp_path)
    write_flow(root, "a", skill_flow("a"))
    write_flow(root, "c", flow_flow("c"))
    flows, schema = load_agent_flows(root)
    # 実行
    files = build_skill_files(root, flows, schema=schema)
    # 検証
    assert [file.path for file in files] == ["skills/a/SKILL.md"]


def test_build_skill_files_when_schema_invalid(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
) -> None:
    """スキーマに合わない（異常系）。"""
    # 準備
    root = write_source(tmp_path)
    write_flow(root, "a", skill_flow("a"))
    broken = skill_flow("b")
    del broken["skill"]
    write_flow(root, "b", broken)
    flows, schema = load_agent_flows(root)
    # 実行
    with pytest.raises(InvalidAgentFlowError) as caught:
        build_skill_files(root, flows, schema=schema)
    # 検証
    problems = caught.value.problems
    assert [problem.file for problem in problems] == ["docs/agent-flow/b.yaml"]
    assert "skill" in problems[0].rule


def test_build_skill_files_when_path_outside(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
) -> None:
    """書き出す先が配信元の外部（異常系）。"""
    # 準備
    root = write_source(tmp_path / "sample")
    write_flow(root, "a", skill_flow("a", skill={"path": "../outside/SKILL.md"}))
    flows, schema = load_agent_flows(root)
    # 実行
    with pytest.raises(InvalidAgentFlowError) as caught:
        build_skill_files(root, flows, schema=schema)
    # 検証
    assert [problem.path for problem in caught.value.problems] == ["skill.path"]


def test_build_skill_files_when_schema_none(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
) -> None:
    """検査のモードではスキーマを検査しない（正常系）。"""
    # 準備
    root = write_source(tmp_path)
    write_flow(root, "a", skill_flow("a", unknown_key="x"))
    flows, _ = load_agent_flows(root)
    # 実行
    files = build_skill_files(root, flows, schema=None)
    # 検証
    assert [file.path for file in files] == ["skills/a/SKILL.md"]


# resolve_steps


def _flow(path: str, data: dict[str, Any]) -> AgentFlowFile:
    """エージェントフローのファイルを作る。"""
    return AgentFlowFile(path=path, data=data)


def test_resolve_steps(
    skill_flow: Callable[..., dict[str, Any]], flow_flow: Callable[..., dict[str, Any]]
) -> None:
    """ref を参照先の工程に置き換える（正常系）。"""
    # 準備
    a = _flow(
        "docs/agent-flow/a.yaml",
        skill_flow(
            "a", steps=[{"name": "進める"}, {"name": "参照する", "ref": "c#steps[取得する]"}]
        ),
    )
    c = _flow("docs/agent-flow/c.yaml", flow_flow("c"))
    # 実行
    steps, problems = resolve_steps(a, {"a": a, "c": c})
    # 検証
    assert steps == [{"name": "進める"}, {"name": "取得する", "body": "取得する。"}]
    assert problems == []


def test_resolve_steps_when_missing(
    skill_flow: Callable[..., dict[str, Any]], flow_flow: Callable[..., dict[str, Any]]
) -> None:
    """参照先の工程が無い（異常系）。"""
    # 準備
    a = _flow(
        "docs/agent-flow/a.yaml",
        skill_flow(
            "a", steps=[{"name": "進める"}, {"name": "参照する", "ref": "c#steps[無い工程]"}]
        ),
    )
    c = _flow("docs/agent-flow/c.yaml", flow_flow("c"))
    # 実行
    _, problems = resolve_steps(a, {"a": a, "c": c})
    # 検証
    assert [problem.path for problem in problems] == ["steps[1].ref"]
    assert "c#steps[無い工程]" in problems[0].rule


def test_resolve_steps_when_cycle(
    skill_flow: Callable[..., dict[str, Any]], flow_flow: Callable[..., dict[str, Any]]
) -> None:
    """同じ工程へ戻る ref（異常系）。"""
    # 準備
    a = _flow(
        "docs/agent-flow/a.yaml",
        skill_flow("a", steps=[{"name": "参照する", "ref": "c#steps[取得する]"}]),
    )
    c = _flow(
        "docs/agent-flow/c.yaml",
        flow_flow("c", steps=[{"name": "取得する", "ref": "d#steps[戻る]"}]),
    )
    d = _flow(
        "docs/agent-flow/d.yaml",
        flow_flow("d", steps=[{"name": "戻る", "ref": "c#steps[取得する]"}]),
    )
    # 実行
    _, problems = resolve_steps(a, {"a": a, "c": c, "d": d})
    # 検証
    assert [problem.path for problem in problems] == ["steps[0].ref"]


# render_skill_md


def test_render_skill_md(skill_flow: Callable[..., dict[str, Any]]) -> None:
    """frontmatter と本文の並び（正常系）。"""
    # 準備
    data = skill_flow(
        "a",
        skill={
            "path": "skills/a/SKILL.md",
            "arguments": [
                {"name": "target", "hint": "[target]", "description": "対象。省くと今のフォルダ"}
            ],
            "allowed_tools": ["Bash(echo *)"],
        },
    )
    steps = [
        {
            "name": "準備する",
            "when": "対象があるとき",
            "body": "準備する。",
            "calls": [
                {"type": "command", "command": "echo {target}"},
                {"type": "tool", "tool": "Read", "args": {"required": ["file_path"]}},
            ],
        },
        {"name": "進める", "body": "進める。"},
    ]
    # 実行
    text = render_skill_md(_flow("docs/agent-flow/a.yaml", data), steps)
    # 検証
    front, body = _split(text)
    assert list(front) == ["name", "description", "argument-hint", "arguments", "allowed-tools"]
    assert front == {
        "name": "a",
        "description": "a を進める",
        "argument-hint": "[target]",
        "arguments": ["target"],
        "allowed-tools": ["Bash(echo *)"],
    }
    assert body == RENDERED_BODY
    assert text.endswith("進める。\n")


def test_render_skill_md_when_minimal() -> None:
    """値が無いキーを置かない（正常系）。"""
    # 準備
    data = {
        "id": "minimal",
        "type": "skill",
        "summary": "最小のスキル",
        "skill": {"path": "skills/minimal/SKILL.md"},
        "steps": [{"name": "進める", "body": "進める。"}],
    }
    # 実行
    text = render_skill_md(_flow("docs/agent-flow/minimal.yaml", data), data["steps"])
    # 検証
    front, body = _split(text)
    assert front == {"name": "minimal", "description": "最小のスキル"}
    assert "\n# minimal\n" in body
    assert "## 引数" not in body


# write_changed


def test_write_changed(tmp_path: Path) -> None:
    """違うものだけを書き出す（正常系）。"""
    # 準備
    b_path = tmp_path / "skills/b/SKILL.md"
    b_path.parent.mkdir(parents=True)
    b_path.write_text("b\n", encoding="utf-8")
    os.utime(b_path, ns=(1_000_000_000, 1_000_000_000))
    files = [
        SkillFile(path="skills/a/SKILL.md", text="a\n"),
        SkillFile(path="skills/b/SKILL.md", text="b\n"),
    ]
    # 実行
    written = write_changed(tmp_path, files)
    # 検証
    assert written == ["skills/a/SKILL.md"]
    assert (tmp_path / "skills/a/SKILL.md").read_text(encoding="utf-8") == "a\n"
    assert b_path.stat().st_mtime_ns == 1_000_000_000


# check_replacement


def _ref_source(
    root: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
    flow_flow: Callable[..., dict[str, Any]],
) -> Path:
    """a の 2 つ目の工程が c の工程を ref で指す配信元を作る。"""
    write_source(root)
    write_flow(
        root,
        "a",
        skill_flow(
            "a", steps=[{"name": "進める"}, {"name": "参照する", "ref": "c#steps[取得する]"}]
        ),
    )
    write_flow(root, "c", flow_flow("c"))
    return root


def test_check_replacement(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
    flow_flow: Callable[..., dict[str, Any]],
) -> None:
    """問題が無い（正常系）。"""
    # 準備
    root = _ref_source(tmp_path, write_source, write_flow, skill_flow, flow_flow)
    text = json.dumps(flow_flow("c", steps=[{"name": "取得する", "body": "書き換えた。"}]))
    before = sorted(path.read_bytes() for path in root.rglob("*") if path.is_file())
    # 実行
    problems = check_replacement(root, text)
    # 検証
    assert problems == []
    assert sorted(path.read_bytes() for path in root.rglob("*") if path.is_file()) == before


def test_check_replacement_when_unbuildable(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
    flow_flow: Callable[..., dict[str, Any]],
) -> None:
    """組み立てられなくなる（異常系）。"""
    # 準備
    root = _ref_source(tmp_path / "sample", write_source, write_flow, skill_flow, flow_flow)
    text = json.dumps(
        skill_flow(
            "a",
            skill={"path": "../outside/SKILL.md"},
            steps=[{"name": "進める"}, {"name": "参照する", "ref": "c#steps[無い工程]"}],
        )
    )
    # 実行
    problems = check_replacement(root, text)
    # 検証
    assert sorted(problem.path for problem in problems) == ["skill.path", "steps[1].ref"]


def test_check_replacement_when_unreadable(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
    flow_flow: Callable[..., dict[str, Any]],
) -> None:
    """標準入力が YAML として読めない（異常系）。"""
    # 準備
    root = _ref_source(tmp_path, write_source, write_flow, skill_flow, flow_flow)
    # 実行
    problems = check_replacement(root, "id: [")
    # 検証
    assert [problem.path for problem in problems] == ["$"]


def test_check_replacement_when_other_unreadable(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
    flow_flow: Callable[..., dict[str, Any]],
) -> None:
    """配信元のほかのエージェントフローが読めない（異常系）。"""
    # 準備
    root = _ref_source(tmp_path, write_source, write_flow, skill_flow, flow_flow)
    (root / "docs/agent-flow/c.yaml").write_text('summary: "unterminated\n', encoding="utf-8")
    text = json.dumps(skill_flow("a", steps=[{"name": "進める", "body": "書き換えた。"}]))
    # 実行
    problems = check_replacement(root, text)
    # 検証
    assert [problem.path for problem in problems] == ["$"]
    assert problems[0].rule.startswith("docs/agent-flow/c.yaml")


def test_check_replacement_when_other_ref_broken(
    tmp_path: Path,
    write_source: Callable[..., Path],
    write_flow: Callable[[Path, str, dict[str, Any]], Path],
    skill_flow: Callable[..., dict[str, Any]],
    flow_flow: Callable[..., dict[str, Any]],
) -> None:
    """書き込む文書の変更でほかのスキルが組み立てられなくなる（異常系）。"""
    # 準備
    root = _ref_source(tmp_path, write_source, write_flow, skill_flow, flow_flow)
    text = json.dumps(flow_flow("c", steps=[{"name": "改名した", "body": "取得する。"}]))
    # 実行
    problems = check_replacement(root, text)
    # 検証
    assert [problem.path for problem in problems] == ["$"]
    assert "docs/agent-flow/a.yaml" in problems[0].rule
    assert "steps[1].ref" in problems[0].rule

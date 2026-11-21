from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from project_index.__main__ import main

if TYPE_CHECKING:
    from collections.abc import Callable

# knowledge の design-schemas/v9.2.0 の agent_flow.schema.yaml・common.schema.yaml の複製
FIXTURES = Path(__file__).parent / "fixtures" / "skill_md"
GENERATED = "<!-- {path} から生成した。このファイルを修正せず、設計書を修正して再生成する -->"

A_FLOW: dict[str, Any] = {
    "id": "a",
    "type": "skill",
    "title": "a のスキル",
    "summary": "a を進める",
    "skill": {
        "path": "skills/a/SKILL.md",
        "arguments": [
            {"name": "target", "hint": "[target]", "description": "対象。省くと今のフォルダ"}
        ],
        "allowed_tools": ["Bash(echo *)"],
    },
    "steps": [
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
    ],
}
B_FLOW: dict[str, Any] = {
    "id": "b",
    "type": "skill",
    "title": "b のスキル",
    "summary": "b を確認する",
    "skill": {"path": "skills/b/SKILL.md"},
    "steps": [{"name": "確認する", "body": "確認する。"}],
}
C_FLOW: dict[str, Any] = {
    "id": "c",
    "type": "flow",
    "summary": "c の共通の工程",
    "condition": "c を呼ぶとき",
    "steps": [{"name": "取得する", "body": "取得する。"}],
}
A_SKILL = f"""\
---
name: a
description: a を進める
argument-hint: '[target]'
arguments:
- target
allowed-tools:
- Bash(echo *)
---

{GENERATED.format(path="docs/agent-flow/a.yaml")}

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

- コマンド `echo {{target}}`
- ツール `Read` `{{required: [file_path]}}`

### 進める

進める。
"""
B_SKILL = f"""\
---
name: b
description: b を確認する
---

{GENERATED.format(path="docs/agent-flow/b.yaml")}

# b のスキル

## 手順

### 確認する

確認する。
"""
SOURCE_CONFIG = {
    "version": "3",
    "name": "sample",
    "documents": [
        {
            "id": "agent_flow",
            "title": "エージェントフロー",
            "paths": ["docs/agent-flow/*.yaml"],
            "exclude": ["index.yaml"],
            "schema": {"source": "schemas", "path": "agent_flow.schema.yaml", "ref": "v1"},
        }
    ],
}


def _dump(value: dict[str, Any]) -> str:
    """辞書を YAML として読める JSON にする。"""
    return json.dumps(value, ensure_ascii=False)


@pytest.fixture
def skill_source(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., Path]:
    """参照先のスキーマの配信元・端末の設定・a・b・c を持つ配信元を作り、配信元の直下へ移る関数を返却する。"""

    def _make(
        flows: dict[str, dict[str, Any]] | None = None,
        schema: dict[str, str] | None = None,
    ) -> Path:
        # タグ v1 のスキーマを持つ配信元（作業ツリーのスキーマは壊し、commit の中身を参照させる）
        schemas = git_repo(
            {
                "project-index.yaml": "name: schemas\ndocuments: []\n",
                "agent_flow.schema.yaml": (FIXTURES / "agent_flow.schema.yaml").read_text(
                    encoding="utf-8"
                ),
                "common.schema.yaml": (FIXTURES / "common.schema.yaml").read_text(encoding="utf-8"),
            },
            name="schemas",
        )
        run_git(schemas, "tag", "v1")
        (schemas / "agent_flow.schema.yaml").write_text("broken: [", encoding="utf-8")
        settings = tmp_path / "settings.yaml"
        settings.write_text(
            _dump(
                {
                    "version": "1",
                    "clone": str(tmp_path),
                    "sources": [{"id": "schemas", "config": str(schemas / "project-index.yaml")}],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("PROJECT_INDEX_CONFIG", str(settings))
        # 配信元（a・b・c と、今のエージェントフローから生成した b の SKILL.md）
        root = tmp_path / "sample"
        config = json.loads(json.dumps(SOURCE_CONFIG))
        if schema is not None:
            config["documents"][0]["schema"] = schema
        (root / "docs/agent-flow").mkdir(parents=True)
        (root / "project-index.yaml").write_text(_dump(config), encoding="utf-8")
        for name, data in (flows or {"a": A_FLOW, "b": B_FLOW, "c": C_FLOW}).items():
            (root / f"docs/agent-flow/{name}.yaml").write_text(_dump(data), encoding="utf-8")
        (root / "skills/b").mkdir(parents=True)
        (root / "skills/b/SKILL.md").write_text(B_SKILL, encoding="utf-8")
        monkeypatch.chdir(root)
        return root

    return _make


def _with_ref(name: str) -> dict[str, Any]:
    """a の 2 つ目の工程を `ref: c#steps[{name}]` にしたエージェントフローを返却する。"""
    flow = json.loads(json.dumps(A_FLOW))
    flow["steps"][1] = {"name": "参照する", "ref": f"c#steps[{name}]"}
    return flow


def test_normal(skill_source: Callable[..., Path], capsys: pytest.CaptureFixture[str]) -> None:
    """組み立てた中身が今の SKILL.md と違うエージェントフローだけ、SKILL.md を書き出す（正常系）。"""
    # 準備
    root = skill_source()
    b_before = (root / "skills/b/SKILL.md").read_bytes()
    # 実行
    code = main(["skill-md"])
    out, _ = capsys.readouterr()
    again = main(["skill-md"])
    again_out, _ = capsys.readouterr()
    # 検証
    assert code == 0
    assert out == "skills/a/SKILL.md\n"
    assert (root / "skills/a/SKILL.md").read_text(encoding="utf-8") == A_SKILL
    assert (root / "skills/b/SKILL.md").read_bytes() == b_before
    assert not (root / "skills/c").exists()
    assert again == 0
    assert again_out == ""


def test_normal_when_step_ref(
    skill_source: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """ref を持つ工程は、参照先の工程の中身に置き換えて書き出す（正常系）。"""
    # 準備
    root = skill_source({"a": _with_ref("取得する"), "b": B_FLOW, "c": C_FLOW})
    # 実行
    code = main(["skill-md"])
    capsys.readouterr()
    # 検証
    text = (root / "skills/a/SKILL.md").read_text(encoding="utf-8")
    assert code == 0
    assert text.endswith("### 取得する\n\n取得する。\n")
    assert "参照する" not in text


def test_normal_when_check_passes(
    skill_source: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """書き込む前のエージェントフローで全ての SKILL.md を組み立てられるときは [] を出す（正常系）。"""
    # 準備
    root = skill_source({"a": _with_ref("取得する"), "b": B_FLOW, "c": C_FLOW})
    changed = json.loads(json.dumps(C_FLOW))
    changed["steps"][0]["body"] = "書き換えた。"
    monkeypatch.setattr(sys, "stdin", io.StringIO(_dump(changed)))
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    # 実行
    code = main(["skill-md", "--check"])
    # 検証
    out, _ = capsys.readouterr()
    assert code == 0
    assert json.loads(out) == []
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_normal_when_check_finds_violations(
    skill_source: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """SKILL.md を組み立てられなくなる書き込みは違反の JSON を出す（正常系）。"""
    # 準備
    root = skill_source({"a": _with_ref("取得する"), "b": B_FLOW, "c": C_FLOW})
    broken = _with_ref("無い工程")
    broken["skill"]["path"] = "../outside/SKILL.md"
    monkeypatch.setattr(sys, "stdin", io.StringIO(_dump(broken)))
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    # 実行
    code = main(["skill-md", "--check"])
    # 検証
    out, _ = capsys.readouterr()
    violations = json.loads(out)
    assert code == 0
    assert sorted(violation["path"] for violation in violations) == ["skill.path", "steps[1].ref"]
    assert any("c#steps[無い工程]" in violation["rule"] for violation in violations)
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    assert not (root.parent / "outside").exists()


def test_error_when_schema_invalid(
    skill_source: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """スキーマに合わないエージェントフローがあれば、どの SKILL.md も書き換えずに終える（異常系）。"""
    # 準備
    broken = json.loads(json.dumps(B_FLOW))
    del broken["skill"]["path"]
    root = skill_source({"a": A_FLOW, "b": broken, "c": C_FLOW})
    b_before = (root / "skills/b/SKILL.md").read_bytes()
    # 実行
    code = main(["skill-md"])
    # 検証
    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert "docs/agent-flow/b.yaml" in err
    assert "path" in err
    assert not (root / "skills/a/SKILL.md").exists()
    assert (root / "skills/b/SKILL.md").read_bytes() == b_before


def test_error_when_doc_unreadable(
    skill_source: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """読めないエージェントフローがあれば、どの SKILL.md も書き換えずに終える（異常系）。"""
    # 準備
    root = skill_source()
    (root / "docs/agent-flow/c.yaml").write_text('summary: "unterminated\n', encoding="utf-8")
    b_before = (root / "skills/b/SKILL.md").read_bytes()
    # 実行
    code = main(["skill-md"])
    # 検証
    _, err = capsys.readouterr()
    assert code == 1
    assert "docs/agent-flow/c.yaml" in err
    assert not (root / "skills/a/SKILL.md").exists()
    assert (root / "skills/b/SKILL.md").read_bytes() == b_before


def test_error_when_step_ref_missing(
    skill_source: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """ref が指す工程が無ければ、どの SKILL.md も書き換えずに終える（異常系）。"""
    # 準備
    root = skill_source({"a": _with_ref("無い工程"), "b": B_FLOW, "c": C_FLOW})
    # 実行
    code = main(["skill-md"])
    # 検証
    _, err = capsys.readouterr()
    assert code == 1
    assert "docs/agent-flow/a.yaml" in err
    assert "c#steps[無い工程]" in err
    assert not (root / "skills/a/SKILL.md").exists()


def test_error_when_path_outside_source(
    skill_source: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """skill.path が配信元の外部を指せば、どの SKILL.md も書き換えずに終える（異常系）。"""
    # 準備
    outside = json.loads(json.dumps(A_FLOW))
    outside["skill"]["path"] = "../outside/SKILL.md"
    root = skill_source({"a": outside, "b": B_FLOW, "c": C_FLOW})
    b_before = (root / "skills/b/SKILL.md").read_bytes()
    # 実行
    code = main(["skill-md"])
    # 検証
    _, err = capsys.readouterr()
    assert code == 1
    assert "docs/agent-flow/a.yaml" in err
    assert "skill.path" in err
    assert not (root.parent / "outside").exists()
    assert (root / "skills/b/SKILL.md").read_bytes() == b_before


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        pytest.param(
            {"source": "nothing", "path": "agent_flow.schema.yaml", "ref": "v1"},
            "nothing:agent_flow.schema.yaml@v1",
            id="source-missing",
        ),
        pytest.param(
            {"source": "schemas", "path": "agent_flow.schema.yaml", "ref": "v9"},
            "schemas:agent_flow.schema.yaml@v9",
            id="ref-missing",
        ),
    ],
)
def test_error_when_schema_unresolvable(
    skill_source: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    schema: dict[str, str],
    expected: str,
) -> None:
    """ほかの配信元を指すスキーマを読み込めなければ、どの SKILL.md も書き換えずに終える（異常系）。"""
    # 準備
    root = skill_source(schema=schema)
    b_before = (root / "skills/b/SKILL.md").read_bytes()
    # 実行
    code = main(["skill-md"])
    # 検証
    _, err = capsys.readouterr()
    assert code == 1
    assert expected in err
    assert not (root / "skills/a/SKILL.md").exists()
    assert (root / "skills/b/SKILL.md").read_bytes() == b_before


def test_normal_when_check_delete(
    skill_source: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ref で埋め込まれるエージェントフローを、参照しているスキルを残して削除すると違反の JSON を出す（正常系）。"""
    # 準備
    root = skill_source({"a": _with_ref("取得する"), "b": B_FLOW, "c": C_FLOW})
    monkeypatch.setenv("PROJECT_INDEX_VALIDATE_ON", "delete")
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    # 実行
    monkeypatch.setenv("PROJECT_INDEX_DELETE_IDS", "c")
    monkeypatch.setattr(sys, "stdin", io.StringIO(_dump(C_FLOW)))
    first_code = main(["skill-md", "--check"])
    first, _ = capsys.readouterr()
    monkeypatch.setenv("PROJECT_INDEX_DELETE_IDS", "a\nc")
    monkeypatch.setattr(sys, "stdin", io.StringIO(_dump(C_FLOW)))
    second_code = main(["skill-md", "--check"])
    second, _ = capsys.readouterr()
    # 検証
    violations = json.loads(first)
    assert (first_code, second_code) == (0, 0)
    assert [violation["path"] for violation in violations] == ["$"]
    assert "docs/agent-flow/a.yaml" in violations[0]["rule"]
    assert "c#steps[取得する]" in violations[0]["rule"]
    assert json.loads(second) == []
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before

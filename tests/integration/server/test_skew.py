from __future__ import annotations

import json
from typing import TYPE_CHECKING

from project_index.__main__ import main

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

BASE = "タスクの保存と取得を受け持ち、保存先や検索の条件を変えるときに参照する"
PARTICLE_O = "タスクの保存と取得を受け持ち、保存先や検索の条件を変えるときを参照する"
PARTICLE_DE = "タスクの保存と取得を受け持ち、保存先や検索の条件を変えるときで参照する"


def _row(path: str, description: str, tags: list[str]) -> str:
    """管理用の YAML の行を 1 つ作る。"""
    return f"  - path: {path}\n    description: {description}\n    tags: [{', '.join(tags)}]\n"


def test_normal(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """管理用の YAML と行の案から、偏りを 3 種類とも出す（正常系）。"""
    # 準備
    rows = [
        _row("a.md", BASE, ["topic:doc"]),
        _row("b.md", PARTICLE_O, ["topic:doc"]),
        _row("c.md", "画面の部品の並びを定める", ["topic:doc", "topic:x"]),
        _row("d.md", "設定の読み込みを受け持つ", ["topic:doc"]),
        _row("e.md", "ログの出し方を定める", ["topic:doc"]),
        _row("f.md", "起動の手順を並べる", ["topic:doc"]),
    ]
    draft = {"path": "g.md", "description": "用語の一覧を持つ", "tags": ["topic:doc"]}
    write_files(
        tmp_path,
        {
            "files.yaml": "files:\n" + "".join(rows),
            "draft.jsonl": json.dumps(draft, ensure_ascii=False) + "\n",
        },
    )
    # 実行
    code = main(
        [
            "skew",
            "--root",
            str(tmp_path),
            "--files-yaml",
            "files.yaml",
            "--draft",
            str(tmp_path / "draft.jsonl"),
        ]
    )
    # 検証
    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["rows"] == 7
    assert [pair["paths"] for pair in output["similar_descriptions"]] == [["a.md", "b.md"]]
    assert output["similar_descriptions"][0]["similarity"] >= 0.9
    assert output["singleton_tags"] == [{"tag": "topic:x", "path": "c.md"}]
    assert output["dominant_tags"] == [{"tag": "topic:doc", "count": 7}]


def test_normal_when_no_skew(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """偏りが無いと、似た組と 1 件だけのタグを空で出す（正常系）。"""
    # 準備
    rows = [
        _row("a.md", "画面の部品の並びを定める", ["topic:a"]),
        _row("b.md", "設定の読み込みを受け持つ", ["topic:a"]),
        _row("c.md", "ログの出し方を定める", ["topic:b"]),
        _row("d.md", "起動の手順を並べる", ["topic:b"]),
        _row("e.md", "用語の一覧を持つ", []),
    ]
    write_files(tmp_path, {"files.yaml": "files:\n" + "".join(rows)})
    # 実行
    code = main(["skew", "--root", str(tmp_path), "--files-yaml", "files.yaml"])
    # 検証
    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output == {
        "rows": 5,
        "similar_descriptions": [],
        "singleton_tags": [],
        "dominant_tags": [],
    }


def test_normal_when_same_path_in_files_yamls(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """管理用の YAML ごとの相対パスが同じ行を、`--root` からのパスで別の行として出す（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "docs/files.yaml": "files:\n" + _row("README.md", "文書の目次", ["topic:d"]),
            "src/files.yaml": "files:\n" + _row("README.md", "コードの説明", ["topic:s"]),
        },
    )
    # 実行
    code = main(
        [
            "skew",
            "--root",
            str(tmp_path),
            "--files-yaml",
            "docs/files.yaml",
            "--files-yaml",
            "src/files.yaml",
        ]
    )
    # 検証
    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["rows"] == 2
    assert output["singleton_tags"] == [
        {"tag": "topic:d", "path": "docs/README.md"},
        {"tag": "topic:s", "path": "src/README.md"},
    ]
    assert output["dominant_tags"] == []


def test_normal_when_only_draft(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--only-draft` を渡すと、行の案を含む組だけを出す（正常系）。"""
    # 準備
    draft: dict[str, object] = {"path": "c.md", "description": PARTICLE_DE, "tags": []}
    write_files(
        tmp_path,
        {
            "files.yaml": "files:\n" + _row("a.md", BASE, []) + _row("b.md", PARTICLE_O, []),
            "draft.jsonl": json.dumps(draft, ensure_ascii=False) + "\n",
        },
    )
    # 実行
    code = main(
        [
            "skew",
            "--root",
            str(tmp_path),
            "--files-yaml",
            "files.yaml",
            "--draft",
            "draft.jsonl",
            "--only-draft",
        ]
    )
    # 検証
    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert sorted(pair["paths"] for pair in output["similar_descriptions"]) == [
        ["a.md", "c.md"],
        ["b.md", "c.md"],
    ]


def test_error_when_input_not_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--files-yaml` のファイルが無いと終了コード 2 で終える（異常系）。"""
    # 準備
    missing = "missing/files.yaml"
    # 実行
    code = main(["skew", "--root", str(tmp_path), "--files-yaml", missing])
    # 検証
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert missing in captured.err

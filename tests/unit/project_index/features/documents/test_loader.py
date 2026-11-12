from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from project_index.features.documents import loader as loader_module
from project_index.features.documents.loader import (
    collect_files,
    documents_from_text,
    load_file,
)
from project_index.features.history.types import FileDates
from project_index.features.sources.types import DocumentTable
from project_index.shared.hashing import content_hash, value_hash


def test_collect_files(tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]) -> None:
    """glob で集める（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "a/x.yaml": "x: 1\n",
            "a/b/y.yaml": "y: 1\n",
            "a/z.md": "# z\n",
            ".git/c.yaml": "c: 1\n",
        },
    )
    table = DocumentTable(id="rules", paths=["a/**/*.yaml"], schema_path="schemas/rule.schema.yaml")
    # 実行
    result = collect_files(tmp_path, table)
    # 検証
    assert result == ["a/b/y.yaml", "a/x.yaml"]


def test_collect_files_when_overlapping_patterns(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """重なる glob（正常系）。"""
    # 準備
    write_files(tmp_path, {"a/x.yaml": "x: 1\n"})
    table = DocumentTable(
        id="rules", paths=["a/*.yaml", "**/x.yaml"], schema_path="schemas/rule.schema.yaml"
    )
    # 実行
    result = collect_files(tmp_path, table)
    # 検証
    assert result == ["a/x.yaml"]


def test_collect_files_when_excluded(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """除外の名前に当たるファイルを外す（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "a/x.md": "# x\n",
            "a/README.md": "# a\n",
            "a/b/README.md": "# b\n",
        },
    )
    table = DocumentTable(
        id="notes",
        paths=["a/**/*.md"],
        schema_path="schemas/rule.schema.yaml",
        exclude=["README.md"],
    )
    # 実行
    result = collect_files(tmp_path, table)
    # 検証
    assert result == ["a/x.md"]


def test_collect_files_when_worktrees(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """ワークツリーのフォルダをたどらない（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "a/x.md": "# x\n",
            ".claude/worktrees/wt/a/x.md": "# x\n",
            ".claude/a.md": "# a\n",
        },
    )
    table = DocumentTable(id="notes", paths=["**/*.md"], schema_path="schemas/rule.schema.yaml")
    # 実行
    result = collect_files(tmp_path, table)
    # 検証
    assert result == [".claude/a.md", "a/x.md"]


def test_collect_files_when_files_given(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """たどったファイルを使う（正常系）。"""
    # 準備
    write_files(tmp_path, {"a/x.yaml": "x: 1\n"})
    walked: list[Path] = []

    def fake_walk_files(root: Path, **kwargs: Any) -> list[str]:
        walked.append(root)
        return []

    monkeypatch.setattr(loader_module, "walk_files", fake_walk_files)
    table = DocumentTable(id="rules", paths=["a/*.yaml"], schema_path="schemas/rule.schema.yaml")
    # 実行
    result = collect_files(tmp_path, table, files=["a/x.yaml", "a/y.yaml"])
    # 検証
    assert result == ["a/x.yaml", "a/y.yaml"]
    assert walked == []


def test_load_file_when_yaml(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """YAML の 1 ファイル 1 文書（正常系）。"""
    # 準備
    text = "id: rule-a\ntitle: A\n"
    write_files(tmp_path, {"rules/a.yaml": text})
    table = DocumentTable(
        id="rules",
        paths=["rules/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        metadata={"name": "title"},
    )
    # 実行
    documents, problems = load_file(tmp_path, "rules/a.yaml", table, source_id="sample")
    # 検証
    assert problems == []
    assert len(documents) == 1
    assert documents[0].id == "rule-a"
    assert documents[0].metadata["name"] == "A"
    assert documents[0].version == content_hash(text)
    assert documents[0].record_index is None


def test_load_file_when_records(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """records と body_file（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "src/files.yaml": "files:\n  - path: a.py\n    tags: [x]\n  - path: b.py\n",
            "src/a.py": "a = 1\n",
            "src/b.py": "b = 2\n",
        },
    )
    table = DocumentTable(
        id="src",
        paths=["src/files.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="files",
        body_file="path",
    )
    # 実行
    documents, problems = load_file(tmp_path, "src/files.yaml", table, source_id="sample")
    # 検証
    assert problems == []
    assert [doc.id for doc in documents] == ["src/a.py", "src/b.py"]
    assert [doc.body for doc in documents] == ["a = 1\n", "b = 2\n"]
    assert [doc.body_path for doc in documents] == ["src/a.py", "src/b.py"]
    assert [doc.record_index for doc in documents] == [0, 1]
    assert documents[0].version == value_hash({"path": "a.py", "tags": ["x"]})


def test_documents_from_text_when_read_body(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """`body_file` の本文の読み方（正常系）。"""
    # 準備
    write_files(tmp_path, {"a.md": "今の本文\n"})
    text = "items:\n  - path: a.md\n"
    table = DocumentTable(
        id="src",
        paths=["index.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="items",
        body_file="path",
    )
    # 実行
    read, read_problems = documents_from_text(
        text,
        tmp_path,
        "index.yaml",
        table,
        source_id="sample",
        read_body={"a.md": "過去の本文"}.get,
    )
    missing, missing_problems = documents_from_text(
        text, tmp_path, "index.yaml", table, source_id="sample", read_body=lambda path: None
    )
    # 検証
    assert read_problems == []
    assert [(doc.body, doc.body_path) for doc in read] == [("過去の本文", "a.md")]
    assert missing == []
    assert [problem.reason for problem in missing_problems] == ["missing_body_file"]


def test_load_file_when_dates(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """日時の優先順位（正常系）。"""
    # 準備
    stamped = "id: {id}\nupdated: 2026-01-02T00:00:00+09:00\n"
    write_files(
        tmp_path,
        {
            "a.yaml": stamped.format(id="a"),
            "b.yaml": stamped.format(id="b"),
            "c.yaml": "id: c\n",
        },
    )
    table = DocumentTable(id="rules", paths=["*.yaml"], schema_path="schemas/rule.schema.yaml")
    dates = {
        "a.yaml": FileDates(
            created=datetime.fromisoformat("2025-12-01T00:00:00+09:00"),
            updated=datetime.fromisoformat("2025-12-05T00:00:00+09:00"),
        )
    }
    # 実行
    doc_a = load_file(tmp_path, "a.yaml", table, source_id="s", dates=dates)[0][0]
    doc_b = load_file(tmp_path, "b.yaml", table, source_id="s", dates=dates)[0][0]
    doc_c = load_file(tmp_path, "c.yaml", table, source_id="s", dates=dates)[0][0]
    # 検証
    assert doc_a.created == datetime.fromisoformat("2025-12-01T00:00:00+09:00")
    assert doc_a.updated == datetime.fromisoformat("2025-12-05T00:00:00+09:00")
    assert doc_b.created is None
    assert doc_b.updated == datetime.fromisoformat("2026-01-02T00:00:00+09:00")
    assert doc_c.created is None
    assert doc_c.updated is None


def test_load_file_when_unreadable(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """読めない YAML（異常系）。"""
    # 準備
    write_files(tmp_path, {"a.yaml": "a: [1\n"})
    table = DocumentTable(id="rules", paths=["*.yaml"], schema_path="schemas/rule.schema.yaml")
    # 実行
    documents, problems = load_file(tmp_path, "a.yaml", table, source_id="sample")
    # 検証
    assert documents == []
    assert problems[0].reason == "unreadable"
    assert problems[0].detail != ""
    assert problems[0].line is not None
    assert problems[0].line >= 1
    assert problems[0].column is not None
    assert problems[0].column >= 1


def test_load_file_when_missing_body_file(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """無い本文のファイル（異常系）。"""
    # 準備
    write_files(
        tmp_path,
        {"src/files.yaml": "files:\n  - path: none.py\n  - path: ../../x.py\n"},
    )
    table = DocumentTable(
        id="src",
        paths=["src/files.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="files",
        body_file="path",
    )
    # 実行
    documents, problems = load_file(tmp_path, "src/files.yaml", table, source_id="sample")
    # 検証
    assert documents == []
    assert [problem.reason for problem in problems] == ["missing_body_file"] * 2


def test_load_file_when_default_name(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """名前の既定（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "rules/a.yaml": "id: rule-a\n",
            "src/files.yaml": "files:\n  - path: a.py\n  - path: b.py\n    name: 部品 B\n",
            "src/a.py": "a = 1\n",
            "src/b.py": "b = 2\n",
            "list.yaml": "items:\n  - x: 1\n",
        },
    )
    rules = DocumentTable(
        id="rules", paths=["rules/*.yaml"], schema_path="schemas/rule.schema.yaml"
    )
    src = DocumentTable(
        id="src",
        paths=["src/files.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="files",
        body_file="path",
    )
    items = DocumentTable(
        id="items", paths=["list.yaml"], schema_path="schemas/rule.schema.yaml", records="items"
    )
    # 実行
    rule_docs = load_file(tmp_path, "rules/a.yaml", rules, source_id="sample")[0]
    src_docs = load_file(tmp_path, "src/files.yaml", src, source_id="sample")[0]
    item_docs = load_file(tmp_path, "list.yaml", items, source_id="sample")[0]
    # 検証
    assert [doc.metadata["name"] for doc in rule_docs] == ["a"]
    assert [doc.metadata["name"] for doc in src_docs] == ["a", "部品 B"]
    assert [doc.metadata["name"] for doc in item_docs] == ["list.yaml#0"]


def test_load_file_when_same_stem(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """同じ名前で拡張子の違うファイルが別の ID の文書になる（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "src/files.yaml": "files:\n  - path: plan.ts\n  - path: plan.css\n",
            "src/plan.ts": "export const plan = 1;\n",
            "src/plan.css": ".plan {}\n",
            "docs/files.yaml": "files:\n  - path: index.md\n",
            "docs/index.md": "# 目次\n",
            "docs/index.yaml": "title: 目次\n",
        },
    )
    src = DocumentTable(
        id="src",
        paths=["src/files.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="files",
        body_file="path",
    )
    docs = DocumentTable(
        id="docs",
        paths=["docs/files.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="files",
        body_file="path",
    )
    index = DocumentTable(
        id="index", paths=["docs/index.yaml"], schema_path="schemas/rule.schema.yaml"
    )
    # 実行
    documents = [
        *load_file(tmp_path, "src/files.yaml", src, source_id="sample")[0],
        *load_file(tmp_path, "docs/files.yaml", docs, source_id="sample")[0],
        *load_file(tmp_path, "docs/index.yaml", index, source_id="sample")[0],
    ]
    # 検証
    assert [doc.id for doc in documents] == [
        "src/plan.ts",
        "src/plan.css",
        "docs/index.md",
        "docs/index.yaml",
    ]
    assert [doc.metadata["name"] for doc in documents] == ["plan", "plan", "index", "index"]


def test_unindexed_files(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """配下の未記載のファイル（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "src/files.yaml": "files:\n  - path: a.py\n",
            "src/a.py": "a = 1\n",
            "src/d.py": "d = 4\n",
            "src/sub/e.py": "e = 5\n",
            "src/node_modules/x.js": "x\n",
        },
    )
    table = DocumentTable(
        id="src",
        paths=["src/files.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="files",
        body_file="path",
    )
    # 実行
    result = loader_module.unindexed_files(tmp_path, "src/files.yaml", ["src/a.py"], table)
    # 検証
    assert result == ["src/d.py", "src/sub/e.py"]


def test_unindexed_files_when_excluded(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """除外の名前に当たるファイルは数えない（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "src/files.yaml": "files:\n  - path: a.py\n",
            "src/a.py": "a = 1\n",
            "src/README.md": "# src\n",
            "src/d.py": "d = 4\n",
        },
    )
    table = DocumentTable(
        id="src",
        paths=["src/files.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="files",
        body_file="path",
        exclude=["README.md"],
    )
    # 実行
    result = loader_module.unindexed_files(tmp_path, "src/files.yaml", ["src/a.py"], table)
    # 検証
    assert result == ["src/d.py"]


def test_unindexed_files_when_matching_exclusion(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """除外の条件に当たるファイルは数えない（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "src/files.yaml": "files:\n  - path: a.py\n",
            "src/a.py": "a = 1\n",
            "src/d.py": "d = 4\n",
            "src/pkg/__init__.py": "",
            "src/uv.lock": "version = 1\n",
            "src/vendor/v.py": "v = 1\n",
        },
    )
    table = DocumentTable(
        id="src",
        paths=["src/files.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="files",
        body_file="path",
    )
    # 実行
    result = loader_module.unindexed_files(tmp_path, "src/files.yaml", ["src/a.py"], table)
    # 検証
    assert result == ["src/d.py"]


def test_unindexed_files_when_files_given(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """たどったファイルのうちフォルダの配下だけを見る（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "src/files.yaml": "files:\n  - path: a.py\n",
            "src/a.py": "a = 1\n",
            "src/d.py": "d = 4\n",
            "docs/x.md": "# x\n",
        },
    )
    walked: list[Path] = []

    def fake_walk_files(root: Path, **kwargs: Any) -> list[str]:
        walked.append(root)
        return []

    monkeypatch.setattr(loader_module, "walk_files", fake_walk_files)
    table = DocumentTable(
        id="src",
        paths=["src/files.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="files",
        body_file="path",
    )
    # 実行
    result = loader_module.unindexed_files(
        tmp_path,
        "src/files.yaml",
        ["src/a.py"],
        table,
        files=["src/files.yaml", "src/a.py", "src/d.py", "docs/x.md"],
    )
    # 検証
    assert result == ["src/d.py"]
    assert walked == []

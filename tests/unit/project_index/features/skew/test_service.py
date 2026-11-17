from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from project_index.features.skew.service import find_skew, load_rows, similarity, to_json
from project_index.features.skew.types import (
    MetadataRow,
    SimilarPair,
    SingletonTag,
    SkewInputError,
    SkewResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

BASE_DESCRIPTION = "タスクの保存と取得を受け持ち、保存先や検索の条件を変えるときに参照する"


def test_load_rows(tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]) -> None:
    """管理用の YAML ごとの相対パスを root からのパスにする（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "docs/files.yaml": "files:\n  - path: README.md\n    tags: [topic:a]\n",
            "src/files.yaml": "files:\n  - path: README.md\n    tags:\n      - name: topic:b\n",
        },
    )
    # 実行
    rows, draft_paths = load_rows(tmp_path, ["docs/files.yaml", "src/files.yaml"])
    # 検証
    assert rows == [
        MetadataRow(path="docs/README.md", description=None, tags=("topic:a",)),
        MetadataRow(path="src/README.md", description=None, tags=("topic:b",)),
    ]
    assert draft_paths == frozenset()


def test_load_rows_when_draft(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """行の案で置き換え、加える（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "files.yaml": "files:\n  - path: a.md\n    description: 旧\n",
            "draft.jsonl": (
                '{"path": "a.md", "description": "新", "tags": []}\n'
                '{"path": "b.md", "description": "追加", "tags": ["topic:x"]}\n'
            ),
        },
    )
    # 実行
    rows, draft_paths = load_rows(tmp_path, ["files.yaml"], draft="draft.jsonl")
    # 検証
    assert rows == [
        MetadataRow(path="a.md", description="新", tags=()),
        MetadataRow(path="b.md", description="追加", tags=("topic:x",)),
    ]
    assert draft_paths == frozenset({"a.md", "b.md"})


def test_load_rows_when_files_yaml_missing(tmp_path: Path) -> None:
    """管理用の YAML が無い（異常系）。"""
    # 準備
    missing = "missing/files.yaml"
    # 実行・検証
    with pytest.raises(SkewInputError, match="ファイルがありません") as error:
        load_rows(tmp_path, [missing])
    assert error.value.path == tmp_path / missing


def test_load_rows_when_draft_invalid(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """行の案が JSON Lines として読めない（異常系）。"""
    # 準備
    write_files(tmp_path, {"files.yaml": "files: []\n", "draft.jsonl": "{\n"})
    # 実行・検証
    with pytest.raises(SkewInputError):
        load_rows(tmp_path, ["files.yaml"], draft="draft.jsonl")


def test_similarity_when_particle_differs() -> None:
    """助詞 1 字だけが違う（正常系）。"""
    # 準備
    other = "タスクの保存と取得を受け持ち、保存先や検索の条件を変えるときを参照する"
    # 実行
    result = similarity(BASE_DESCRIPTION, other)
    # 検証
    assert result == pytest.approx(0.9375)


def test_similarity_when_normalized() -> None:
    """全角・大文字・記号の違いを無視する（正常系）。"""
    # 準備
    left = "ＡＢＣ の設定。"
    right = "abcの設定"
    # 実行
    result = similarity(left, right)
    # 検証
    assert result == 1.0


def test_similarity_when_empty() -> None:
    """空文字（正常系）。"""
    # 準備
    left = ""
    right = "。"
    # 実行
    result = similarity(left, right)
    # 検証
    assert result == 0.0


def test_find_skew() -> None:
    """3 種類の偏りを出す（正常系）。"""
    # 準備
    rows = [
        MetadataRow(path="a.md", description=BASE_DESCRIPTION, tags=("topic:doc",)),
        MetadataRow(
            path="b.md",
            description="タスクの保存と取得を受け持ち、保存先や検索の条件を変えるときを参照する",
            tags=("topic:doc",),
        ),
        MetadataRow(path="c.md", description="画面の部品の並びを定める", tags=("topic:doc", "topic:x")),
        MetadataRow(path="d.md", description="設定の読み込みを受け持つ", tags=("topic:doc",)),
        MetadataRow(path="e.md", description="ログの出し方を定める", tags=("topic:doc",)),
        MetadataRow(path="f.md", description="起動の手順を並べる", tags=("topic:doc",)),
        MetadataRow(path="g.md", description="用語の一覧を持つ", tags=("topic:doc",)),
    ]
    # 実行
    result = find_skew(rows)
    # 検証
    assert result.rows == 7
    assert [pair.paths for pair in result.similar_descriptions] == [("a.md", "b.md")]
    assert result.singleton_tags == (SingletonTag(tag="topic:x", path="c.md"),)
    assert [(tag.tag, tag.count) for tag in result.dominant_tags] == [("topic:doc", 7)]


def test_find_skew_when_only_draft() -> None:
    """行の案を含む組だけ比べる（正常系）。"""
    # 準備
    rows = [
        MetadataRow(path="a.md", description=BASE_DESCRIPTION, tags=()),
        MetadataRow(
            path="b.md",
            description="タスクの保存と取得を受け持ち、保存先や検索の条件を変えるときを参照する",
            tags=(),
        ),
        MetadataRow(
            path="c.md",
            description="タスクの保存と取得を受け持ち、保存先や検索の条件を変えるときで参照する",
            tags=(),
        ),
    ]
    # 実行
    result = find_skew(rows, draft_paths=frozenset({"c.md"}), only_draft=True)
    # 検証
    assert [pair.paths for pair in result.similar_descriptions] == [
        ("a.md", "c.md"),
        ("b.md", "c.md"),
    ]


def test_find_skew_when_singleton_also_half() -> None:
    """1 件だけのタグは半数以上に出さない（正常系）。"""
    # 準備
    rows = [
        MetadataRow(path="docs/README.md", description="文書の目次", tags=("topic:d",)),
        MetadataRow(path="src/README.md", description="コードの説明", tags=("topic:s",)),
    ]
    # 実行
    result = find_skew(rows)
    # 検証
    assert result.singleton_tags == (
        SingletonTag(tag="topic:d", path="docs/README.md"),
        SingletonTag(tag="topic:s", path="src/README.md"),
    )
    assert result.dominant_tags == ()


def test_find_skew_when_no_description() -> None:
    """description を持たない行は比べない（正常系）。"""
    # 準備
    rows = [
        MetadataRow(path="a.md", description=None, tags=()),
        MetadataRow(path="b.md", description=None, tags=()),
    ]
    # 実行
    result = find_skew(rows)
    # 検証
    assert result.similar_descriptions == ()
    assert result.rows == 2


def test_to_json() -> None:
    """インターフェース定義の形（正常系）。"""
    # 準備
    result = SkewResult(
        rows=2,
        similar_descriptions=(SimilarPair(paths=("あ.md", "い.md"), similarity=0.95),),
        singleton_tags=(),
        dominant_tags=(),
    )
    # 実行
    text = to_json(result)
    # 検証
    assert json.loads(text) == {
        "rows": 2,
        "similar_descriptions": [{"paths": ["あ.md", "い.md"], "similarity": 0.95}],
        "singleton_tags": [],
        "dominant_tags": [],
    }
    assert "あ.md" in text

from __future__ import annotations

import pytest

from project_index.features.write.references import (
    renamed_path,
    rewrite_body_references,
    rewrite_references,
)

from project_index.features.write.types import ReferenceChange
from project_index.shared.yaml_io import load_roundtrip


def test_renamed_path() -> None:
    """ファイル名の ID の部分だけを変える（正常系）。"""
    # 実行
    interface = renamed_path("docs/interface/IF-6.yaml", old_id="IF-6", new_id="IF-9")
    module = renamed_path("docs/module/MOD-1.py.yaml", old_id="MOD-1", new_id="MOD-2")
    # 検証
    assert interface == "docs/interface/IF-9.yaml"
    assert module == "docs/module/MOD-2.py.yaml"


def test_renamed_path_when_name_differs() -> None:
    """ファイル名が旧 ID で始まらない（正常系）。"""
    # 実行
    rule = renamed_path("docs/rule/ドキュメント管理.yaml", old_id="IF-6", new_id="IF-9")
    longer = renamed_path("docs/interface/IF-60.yaml", old_id="IF-6", new_id="IF-9")
    # 検証
    assert rule is None
    assert longer is None


def test_rewrite_references() -> None:
    """ID で指す 4 種類の箇所（正常系）。"""
    # 準備
    content = load_roundtrip(
        "related:\n"
        "  - to: doc-2\n"
        "  - to: doc-2\n"
        "    source: other\n"
        "ref: doc-2#items[a]\n"
        "body: |-\n"
        "  [文書 2](id:doc-2)\n"
        '  click N href "id:doc-2#items[a]"\n'
        "  [文書 20](id:doc-20)\n"
    )
    # 実行
    changes = rewrite_references(
        content,
        related_column="related",
        old_id="doc-2",
        new_id="doc-9",
        moved=None,
        base_dir="docs",
        skip=["id"],
    )
    # 検証
    assert content["related"][0]["to"] == "doc-9"
    assert content["related"][1]["to"] == "doc-2"
    assert content["ref"] == "doc-9#items[a]"
    assert content["body"] == (
        '[文書 2](id:doc-9)\nclick N href "id:doc-9#items[a]"\n[文書 20](id:doc-20)'
    )
    assert len(changes) == 4
    assert changes[0] == ReferenceChange(path="related[0].to", before="doc-2", after="doc-9")


def test_rewrite_references_when_moved() -> None:
    """パスで指す値（正常系）。"""
    # 準備
    content = load_roundtrip(
        "items:\n"
        "  - page: doc-2.yaml\n"
        "  - page: doc-20.yaml\n"
        "body: |-\n"
        "  [文書 2](./doc-2.yaml)\n"
        "  文の途中の doc-2.yaml は変えない\n"
    )
    # 実行
    changes = rewrite_references(
        content,
        related_column="related",
        old_id="doc-2",
        new_id="doc-2",
        moved=("docs/doc-2.yaml", "docs/old/doc-2.yaml"),
        base_dir="docs",
        skip=["id"],
    )
    # 検証
    assert content["items"][0]["page"] == "old/doc-2.yaml"
    assert content["items"][1]["page"] == "doc-20.yaml"
    assert content["body"] == "[文書 2](./old/doc-2.yaml)\n文の途中の doc-2.yaml は変えない"
    assert len(changes) == 2


def test_rewrite_references_when_skipped() -> None:
    """ID の列と body_file の列は書き換えない（正常系）。"""
    # 準備
    content = load_roundtrip("id: doc-2#x\npath: doc-2.yaml\n")
    # 実行
    changes = rewrite_references(
        content,
        related_column="related",
        old_id="doc-2",
        new_id="doc-9",
        moved=("docs/doc-2.yaml", "docs/doc-9.yaml"),
        base_dir="docs",
        skip=["id", "path"],
    )
    # 検証
    assert content["id"] == "doc-2#x"
    assert content["path"] == "doc-2.yaml"
    assert changes == []


def test_rewrite_body_references() -> None:
    """本文の ID のリンクと相対パスのリンク（正常系）。"""
    # 準備
    body = (
        "[文書 2](id:doc-2#items[a])\n"
        "[文書 2](../docs/doc-2.yaml)\n"
        "[文書 20](id:doc-20)\n"
        "文の途中の doc-2\n"
    )
    # 実行
    after, changes = rewrite_body_references(
        body,
        old_id="doc-2",
        new_id="doc-9",
        moved=("docs/doc-2.yaml", "docs/doc-9.yaml"),
        base_dir="notes",
    )
    # 検証
    assert after == (
        "[文書 2](id:doc-9#items[a])\n"
        "[文書 2](../docs/doc-9.yaml)\n"
        "[文書 20](id:doc-20)\n"
        "文の途中の doc-2\n"
    )
    assert changes == [
        ReferenceChange(path="@body", before="id:doc-2", after="id:doc-9"),
        ReferenceChange(path="@body", before="../docs/doc-2.yaml", after="../docs/doc-9.yaml"),
    ]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("doc-2.yaml という文だけ\n", id="no_link"),
        pytest.param("../docs/doc-2.yaml", id="whole_body_is_path"),
    ],
)
def test_rewrite_body_references_when_unchanged(body: str) -> None:
    """指すリンクが無い（正常系）。"""
    # 実行
    after, changes = rewrite_body_references(
        body,
        old_id="doc-2",
        new_id="doc-9",
        moved=("docs/doc-2.yaml", "docs/doc-9.yaml"),
        base_dir="notes",
    )
    # 検証
    assert after == body
    assert changes == []

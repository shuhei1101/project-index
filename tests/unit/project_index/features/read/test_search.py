from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.read.search import search_words

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.documents.types import Document


def test_search_words(make_document: Callable[..., Document]) -> None:
    """全ての語を含む文書だけ（正常系）。"""
    # 準備
    both = make_document(
        id="both", path="docs/both.yaml", body="先頭の行\nfoo の説明\nbar の説明\n"
    )
    only_foo = make_document(id="only-foo", path="docs/only-foo.yaml", body="foo だけ\n")
    # 実行
    result = search_words([both, only_foo], "foo bar", 20)
    # 検証
    assert result.total_count == 1
    assert result.items[0].path == "docs/both"
    assert any("foo" in line or "bar" in line for line in result.items[0].snippets)

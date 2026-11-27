from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.read.search import SNIPPETS_PER_DOC, search_words

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


def test_search_words_when_record(make_document: Callable[..., Document]) -> None:
    """行の文書の ID とファイルのパスを返す（正常系）。"""
    # 準備
    first = make_document(id="term-1", path="terms.yaml", record_index=0, body="name: alpha\n")
    second = make_document(id="term-2", path="terms.yaml", record_index=1, body="name: beta\n")
    # 実行
    result = search_words([first, second], "beta", 20)
    # 検証
    assert result.total_count == 1
    assert result.items[0].id == "term-2"
    assert result.items[0].file_path == "terms.yaml"
    assert result.items[0].path == "terms/term-2"


def test_search_words_when_excluded(make_document: Callable[..., Document]) -> None:
    """除く文書を既定で除き、指定で excluded を付けて返却する（正常系）。"""
    # 準備
    a1 = make_document(id="a1", path="assets/a1.yaml", body="夕焼けの背景\n")
    a2 = make_document(id="a2", path="assets/a2.yaml", body="夕焼けの古い背景\n")
    # 実行
    default = search_words([a1, a2], "夕焼け", 20, excluded=[False, True])
    included = search_words([a1, a2], "夕焼け", 20, excluded=[False, True], include_excluded=True)
    # 検証
    assert default.total_count == 1
    assert [item.id for item in default.items] == ["a1"]
    assert default.excluded_count == 1
    assert included.total_count == 2
    assert [(item.id, item.excluded) for item in included.items] == [("a1", None), ("a2", True)]
    assert included.excluded_count is None


def test_search_words_when_many_matches(make_document: Callable[..., Document]) -> None:
    """一致した行の数を snippets の上限に関わらず数える（正常系）。"""
    # 準備
    gap = "なし\nなし\n"
    body = gap.join(["foo 1\n", "bar 2\n", "foo bar 3\n", "foo 4\n", "bar 5\n"])
    in_body = make_document(id="in-body", path="docs/in-body.yaml", body=body)
    name_only = make_document(
        id="name-only",
        path="docs/name-only.yaml",
        body="",
        data={"id": "name-only", "name": "foo bar"},
        metadata={"id": "name-only", "name": "foo bar"},
    )
    # 実行
    result = search_words([in_body, name_only], "foo bar", 20)
    # 検証
    by_id = {item.id: item for item in result.items}
    assert len(by_id["in-body"].snippets) == SNIPPETS_PER_DOC
    assert by_id["in-body"].match_count == 5
    assert by_id["name-only"].match_count == 0

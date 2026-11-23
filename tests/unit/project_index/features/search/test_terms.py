from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.documents.store import DocumentStore
from project_index.features.history.snapshot import SnapshotStore
from project_index.features.sources.types import DocumentTable, ServedSource, SourceConfig

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.sources.registry import SourceRegistry

TERM_DOCS = {
    "terms/scope.yaml": (
        "id: scope\nname: 作業範囲\ndescription: 触ってよい範囲\naliases: [scope, 担当範囲]\n"
    ),
    "terms/broken.yaml": "id: broken\nname: 壊れた用語\ndescription: 型の違う別名\naliases: 3\n",
}


def _sample(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    *,
    alias_type: str | None,
) -> ServedSource:
    """用語の文書 2 件を置いた行 terms を持つ配信元 sample を作る。"""
    root = tmp_path / "sample"
    write_files(root, TERM_DOCS)
    table = DocumentTable(
        id="terms",
        paths=["terms/*.yaml"],
        schema_path="schemas/term.schema.yaml",
        alias_type=alias_type,
    )
    return make_served_source(root=root, config=make_source_config(documents=[table]))


def test_list_match_words(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """用語の語と違反した文書の除外（正常系）。"""
    from project_index.features.search.terms import list_match_words
    from project_index.features.search.types import MatchWordsRequest

    # 準備
    source = _sample(
        tmp_path, write_files, make_source_config, make_served_source, alias_type="term"
    )
    store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
    request = MatchWordsRequest(source="sample", cwd=str(source.root))
    # 実行
    result = list_match_words(request, registry=make_registry(source), store=store)
    # 検証
    assert [(word.word, word.id) for word in result.words] == [
        ("作業範囲", "scope"),
        ("scope", "scope"),
        ("担当範囲", "scope"),
    ]


def test_list_match_words_when_no_alias_rows(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """用語の種類が無い（正常系）。"""
    from project_index.features.search.terms import list_match_words
    from project_index.features.search.types import MatchWordsRequest

    # 準備
    source = _sample(tmp_path, write_files, make_source_config, make_served_source, alias_type=None)
    store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
    request = MatchWordsRequest(source="sample", cwd=str(source.root))
    # 実行
    result = list_match_words(request, registry=make_registry(source), store=store)
    # 検証
    assert result.words == []


def test_render_match_words_markdown() -> None:
    """表と空（正常系）。"""
    from project_index.features.documents.types import MatchWord
    from project_index.features.search.terms import render_match_words_markdown
    from project_index.features.search.types import MatchWordsResult

    # 準備
    words = MatchWordsResult(
        words=[
            MatchWord(word="作業範囲", id="glossary/scope", kind="name"),
            MatchWord(word="scope", id="glossary/scope", kind="alias"),
            MatchWord(word="担当範囲", id="glossary/scope", kind="alias"),
        ]
    )
    # 実行
    results = [render_match_words_markdown(words), render_match_words_markdown(MatchWordsResult())]
    # 検証
    assert results[0].splitlines() == [
        "| 単語 | 文書 | 種類 |",
        "| --- | --- | --- |",
        "| 作業範囲 | glossary/scope | name |",
        "| scope | glossary/scope | alias |",
        "| 担当範囲 | glossary/scope | alias |",
    ]
    assert results[1] == "用語はありません"


ASSET_TERM_DOCS = {
    "assets/a1.yaml": "id: a1\ntitle: アセット1\nsummary: 使用中のアセット\nstate: active\n",
    "assets/a2.yaml": "id: a2\ntitle: アセット2\nsummary: 使用しなくなったアセット\nstate: inactive\n",
}


def test_list_match_words_when_search_excluded(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """除く文書の単語を既定で除き、指定で excluded を付ける（正常系）。"""
    from project_index.features.search.terms import list_match_words
    from project_index.features.search.types import MatchWordsRequest

    # 準備
    root = tmp_path / "sample"
    write_files(root, ASSET_TERM_DOCS)
    table = DocumentTable(
        id="assets",
        paths=["assets/*.yaml"],
        schema_path="schemas/term.schema.yaml",
        metadata={"status": "state", "name": "title", "description": "summary"},
        alias_type="term",
        search_exclude={"field": "status", "op": "eq", "values": ["inactive"]},
    )
    source = make_served_source(root=root, config=make_source_config(documents=[table]))
    store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
    registry = make_registry(source)
    # 実行
    default = list_match_words(
        MatchWordsRequest(source="sample", cwd=str(root)), registry=registry, store=store
    )
    included = list_match_words(
        MatchWordsRequest(source="sample", cwd=str(root), include_excluded=True),
        registry=registry,
        store=store,
    )
    # 検証
    assert [(word.word, word.id) for word in default.words] == [("アセット1", "a1")]
    assert default.excluded_count == 1
    assert [(word.word, word.excluded) for word in included.words] == [
        ("アセット1", None),
        ("アセット2", True),
    ]
    assert included.excluded_count is None


def test_render_match_words_markdown_when_excluded() -> None:
    """除外の列と除いた件数の通知（正常系）。"""
    from project_index.features.documents.types import MatchWord
    from project_index.features.search.terms import render_match_words_markdown
    from project_index.features.search.types import MatchWordsResult

    # 準備
    included = MatchWordsResult(
        words=[
            MatchWord(word="アセット1", id="a1", kind="name"),
            MatchWord(word="アセット2", id="a2", kind="name", excluded=True),
        ]
    )
    counted = MatchWordsResult(
        words=[MatchWord(word="アセット1", id="a1", kind="name")], excluded_count=1
    )
    # 実行
    included_text = render_match_words_markdown(included)
    counted_text = render_match_words_markdown(counted)
    # 検証
    assert included_text == (
        "| 単語 | 文書 | 種類 | 除外 |\n"
        "| --- | --- | --- | --- |\n"
        "| アセット1 | a1 | name |  |\n"
        "| アセット2 | a2 | name | ✓ |"
    )
    assert counted_text == (
        "| 単語 | 文書 | 種類 |\n"
        "| --- | --- | --- |\n"
        "| アセット1 | a1 | name |\n"
        "\n"
        "既定の検索から 1 件を除きました。include_excluded: true で取得できます"
    )

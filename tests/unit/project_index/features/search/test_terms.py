from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from project_index.features.documents.store import DocumentStore
from project_index.features.history.snapshot import SnapshotStore
from project_index.features.sources.registry import SourceRegistry
from project_index.features.sources.types import DocumentTable, ServedSource, SourceConfig

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

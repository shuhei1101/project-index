from __future__ import annotations

from collections.abc import Callable
from typing import Any

from project_index.features.documents.types import Document
from project_index.features.sources.types import DocumentTable, ServedSource, SourceConfig


def _alias_document(
    make_document: Callable[..., Document], doc_id: str, kind: str, path: str, **metadata: Any
) -> Document:
    """`metadata` にエイリアスのキーを持つ文書を作る。"""
    values = {"id": doc_id, **metadata}
    return make_document(id=doc_id, kind=kind, path=path, data=values, metadata=values)


def _alias_tables() -> list[DocumentTable]:
    """`alias_type: term` の行 terms・`alias_type: doc` の行 refs・`alias_type` の無い行 rules を返す。"""
    return [
        DocumentTable(
            id="terms",
            paths=["docs/term/*.yaml"],
            schema_path="schemas/term.schema.yaml",
            alias_type="term",
        ),
        DocumentTable(
            id="refs",
            paths=["docs/ref/*.yaml"],
            schema_path="schemas/term.schema.yaml",
            alias_type="doc",
        ),
        DocumentTable(
            id="rules", paths=["docs/rule/*.yaml"], schema_path="schemas/rule.schema.yaml"
        ),
    ]


def test_alias_schema() -> None:
    """同梱したスキーマ（正常系）。"""
    from project_index.features.documents.aliases import alias_schema

    # 実行
    result = alias_schema()
    # 検証
    keys = result["$defs"]["alias"]["properties"]["metadata"]["properties"]
    assert {"name", "aliases", "description", "avoid", "replacement"} <= set(keys)
    assert len(result["$defs"]["alias"]["properties"]["alias_type"]["enum"]) == 9


def test_alias_schema_version() -> None:
    """取り込み元のタグ（正常系）。"""
    from project_index.features.documents.aliases import alias_schema_version

    # 実行
    result = alias_schema_version()
    # 検証
    assert result == "v0.3.0"


def test_check_alias_document(make_document: Callable[..., Document]) -> None:
    """通る用語（正常系）。"""
    from project_index.features.documents.aliases import check_alias_document

    # 準備
    document = _alias_document(
        make_document,
        "scope",
        "terms",
        "docs/term/scope.yaml",
        alias_type="term",
        name="作業範囲",
        aliases=["scope", "担当範囲"],
        description="触ってよい範囲",
    )
    # 実行
    result = check_alias_document(document)
    # 検証
    assert result == []


def test_check_alias_document_when_aliases_number(make_document: Callable[..., Document]) -> None:
    """別名が数値（異常系）。"""
    from project_index.features.documents.aliases import check_alias_document

    # 準備
    document = _alias_document(
        make_document,
        "broken",
        "terms",
        "docs/term/broken.yaml",
        alias_type="term",
        name="壊れた用語",
        aliases=3,
        description="型の違う別名",
    )
    # 実行
    result = check_alias_document(document)
    # 検証
    assert [(item.path, item.rule, item.doc) for item in result] == [
        ("aliases", "文字列か文字列の並びではありません", "docs/term/broken.yaml")
    ]


def test_check_alias_document_when_required_missing(
    make_document: Callable[..., Document],
) -> None:
    """引用の種類の必須が無い（異常系）。"""
    from project_index.features.documents.aliases import check_alias_document

    # 準備
    command = _alias_document(
        make_document,
        "serve",
        "commands",
        "docs/command/serve.yaml",
        alias_type="command",
        name="起動",
    )
    env = _alias_document(
        make_document, "local", "envs", "docs/env/local.yaml", alias_type="env", name="手元"
    )
    # 実行
    results = [check_alias_document(command), check_alias_document(env)]
    # 検証
    assert [[(item.path, item.rule) for item in result] for result in results] == [
        [("command", "必須のキーが無い")],
        [("url", "url・port のどれか 1 つが要ります")],
    ]


def test_check_alias_document_when_aliases_string(make_document: Callable[..., Document]) -> None:
    """別名が文字列（正常系）。"""
    from project_index.features.documents.aliases import check_alias_document

    # 準備
    document = _alias_document(
        make_document,
        "settings",
        "refs",
        "docs/ref/settings.yaml",
        alias_type="doc",
        name="設定のリファレンス",
        aliases="settings",
        description="設定のキーの一覧",
    )
    # 実行
    result = check_alias_document(document)
    # 検証
    assert result == []


def test_collect_aliases(
    make_document: Callable[..., Document],
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> None:
    """用語と文書の別名と違反（正常系）。"""
    from project_index.features.documents.aliases import collect_aliases

    # 準備
    source = make_served_source(config=make_source_config(documents=_alias_tables()))
    documents = [
        _alias_document(
            make_document,
            "scope",
            "terms",
            "docs/term/scope.yaml",
            alias_type="term",
            name="作業範囲",
            aliases=["scope", "担当範囲"],
            avoid=["担当領域"],
            description="触ってよい範囲",
        ),
        _alias_document(
            make_document,
            "broken",
            "terms",
            "docs/term/broken.yaml",
            alias_type="term",
            name="壊れた用語",
            aliases=3,
            description="型の違う別名",
        ),
        _alias_document(
            make_document,
            "settings",
            "refs",
            "docs/ref/settings.yaml",
            alias_type="doc",
            name="設定のリファレンス",
            aliases="settings",
            description="設定のキーの一覧",
        ),
        _alias_document(make_document, "doc-1", "rules", "docs/rule/doc-1.yaml", name="文書 1"),
    ]
    # 実行
    result = collect_aliases(source, documents)
    # 検証
    assert [(entry.id, entry.aliases, entry.avoid) for entry in result.entries] == [
        ("scope", ["scope", "担当範囲"], ["担当領域"]),
        ("settings", ["settings"], None),
    ]
    assert [item.doc for item in result.violations] == ["docs/term/broken.yaml"]
    assert result.has_alias_rows is True


def test_collect_aliases_when_no_alias_rows(
    make_document: Callable[..., Document],
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> None:
    """エイリアスの行が無い（正常系）。"""
    from project_index.features.documents.aliases import collect_aliases

    # 準備
    source = make_served_source(config=make_source_config(documents=_alias_tables()[2:]))
    documents = [
        _alias_document(make_document, "doc-1", "rules", "docs/rule/doc-1.yaml", name="文書 1")
    ]
    # 実行
    result = collect_aliases(source, documents)
    # 検証
    assert result.entries == []
    assert result.violations == []
    assert result.has_alias_rows is False


def _scope_entry() -> Any:
    """「作業範囲」（`aliases: [scope, 担当範囲]`）のエイリアスを作る。"""
    from project_index.features.documents.types import AliasEntry

    return AliasEntry(
        id="scope",
        name="作業範囲",
        aliases=["scope", "担当範囲"],
        description="触ってよい範囲",
        alias_type="term",
    )


def test_match_words() -> None:
    """名前と別名（正常系）。"""
    from project_index.features.documents.aliases import match_words

    # 準備
    entries = [_scope_entry()]
    # 実行
    result = match_words(entries)
    # 検証
    assert [(word.word, word.kind, word.id) for word in result] == [
        ("作業範囲", "name", "scope"),
        ("scope", "alias", "scope"),
        ("担当範囲", "alias", "scope"),
    ]


def test_term_ids() -> None:
    """正規化した完全一致（正常系）。"""
    from project_index.features.documents.aliases import term_ids

    # 準備
    entries = [_scope_entry()]
    # 実行
    results = [term_ids(entries, "担当範囲"), term_ids(entries, "SCOPE"), term_ids(entries, "担当")]
    # 検証
    assert results == [{"scope"}, {"scope"}, set()]

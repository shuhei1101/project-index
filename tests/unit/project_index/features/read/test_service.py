from __future__ import annotations

import dataclasses
from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from project_index.features.documents.types import LoadProblem, LoadResult
from project_index.features.read.paths import read_target
from project_index.features.read.service import (
    get_decision,
    get_document,
    get_source_config,
    list_decisions,
    list_documents,
)
from project_index.features.sources.types import DirectCommitConfig, DocumentTable, ScriptEntry
from project_index.shared.errors import DecisionNotFoundError, DocumentNotFoundError
from project_index.shared.hashing import value_hash
from tests.unit.project_index.conftest import notes_db_table

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.access.types import Target
    from project_index.features.documents.types import Document

REVISION_TIME = datetime.fromisoformat("2026-10-04T12:00:00+09:00")

NOTES_TABLES = [
    DocumentTable(id="rules", paths=["docs/*.yaml"], schema_path="schemas/rule.schema.yaml"),
    DocumentTable(
        id="notes",
        paths=["notes/files.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="files",
        body_file="path",
    ),
]
NOTES_FILES = {
    "schemas/rule.schema.yaml": "type: object\n",
    "docs/a.yaml": "id: a\nname: A\n",
    "notes/files.yaml": "files:\n  - path: guide.md\n",
    "notes/guide.md": "# Guide\n",
}
TERMS_TABLES = [
    DocumentTable(
        id="terms", paths=["terms.yaml"], schema_path="schemas/terms.schema.yaml", records="terms"
    ),
]
TERMS_FILES = {
    "schemas/terms.schema.yaml": "type: object\n",
    "terms.yaml": "terms:\n  - id: term-1\n    name: alpha\n  - id: term-2\n    name: beta\n",
}
LINKS_TABLES = [
    DocumentTable(
        id="design",
        paths=["design/*.yaml"],
        schema_path="schemas/design.schema.yaml",
        metadata={"related": "links"},
        alias_type="term",
    ),
]
LINKS_FILES = {
    "schemas/design.schema.yaml": "type: object\n",
    "design/D-1.yaml": "id: D-1\nname: タスクの保存\nlinks:\n  - to: D-2\n",
}
SCHEMA_TABLES = [
    DocumentTable(id="design", paths=["design/*.yaml"], schema_path="schemas/design.schema.yaml"),
    DocumentTable(
        id="files_guide",
        paths=["files.yaml"],
        schema_path="schemas/files.schema.yaml",
        records="files",
        body_file="path",
    ),
]
SCHEMA_FILES = {
    "schemas/design.schema.yaml": (
        "type: object\n"
        "properties:\n"
        "  title:\n"
        "    $ref: '#/$defs/title'\n"
        "$defs:\n"
        "  title:\n"
        "    type: string\n"
    ),
    "schemas/files.schema.yaml": (
        "type: object\n"
        "properties:\n"
        "  files:\n"
        "    type: array\n"
        "    items:\n"
        "      type: object\n"
        "      required: [path]\n"
    ),
    "design/d-1.yaml": "id: d-1\ntitle: D\n",
    "files.yaml": "files:\n  - path: guide.md\n",
    "guide.md": "# Guide\n",
}


def _target(env: SimpleNamespace) -> Target:
    """配信元 sample の default_ref の読み取りの場所を返す。"""
    target, _ = read_target("sample", None, registry=env.handlers.registry)
    return target


def test_get_source_config(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """画面が使うキーだけを返す（正常系）。"""
    # 準備
    nav = {"tabs": [{"title": "規約", "items": [{"auto": {"document": "rules"}}]}]}
    env = make_view_env(
        converters=[ScriptEntry(id="c", run=["python3", "scripts/c.py"])],
        nav=nav,
        decision_folders=["tmp/a"],
    )
    # 実行
    response = get_source_config(_target(env), store=env.handlers.store)
    # 検証
    dumped = response.model_dump()
    assert dumped["nav"] == nav
    assert dumped["decisions"] == {"folders": ["tmp/a"]}
    assert [row["id"] for row in dumped["documents"]] == ["rules"]
    assert dumped["diff"] == {"ignore_keys": ["updated"]}
    assert dumped["schemas"] is None
    assert "converters" not in dumped
    assert "python3" not in str(dumped)


def test_get_source_config_when_no_decisions(
    make_view_env: Callable[..., SimpleNamespace],
) -> None:
    """decisions を持たない（正常系）。"""
    # 準備
    env = make_view_env()
    # 実行
    response = get_source_config(_target(env), store=env.handlers.store)
    # 検証
    assert response.decisions == {"folders": []}


@pytest.mark.parametrize(
    ("diff_ignore_keys", "expected"),
    [
        pytest.param(["updated", "rev"], {"ignore_keys": ["updated", "rev"]}, id="written"),
        pytest.param(None, {"ignore_keys": ["updated"]}, id="default"),
    ],
)
def test_get_source_config_when_diff(
    make_view_env: Callable[..., SimpleNamespace],
    diff_ignore_keys: list[str] | None,
    expected: dict[str, list[str]],
) -> None:
    """diff の値と既定の値（正常系）。"""
    # 準備
    env = make_view_env(diff_ignore_keys=diff_ignore_keys)
    # 実行
    response = get_source_config(_target(env), store=env.handlers.store)
    # 検証
    assert response.diff == expected


@pytest.mark.parametrize(
    ("direct_commit", "expected"),
    [
        pytest.param(
            DirectCommitConfig(
                branch="main",
                kinds=["note", "spec", "memo"],
                metadata_only_kinds=["spec", "memo"],
            ),
            ["spec", "memo"],
            id="metadata_only",
        ),
        pytest.param(None, [], id="no_direct_commit"),
    ],
)
def test_get_source_config_when_metadata_only_kinds(
    make_view_env: Callable[..., SimpleNamespace],
    direct_commit: DirectCommitConfig | None,
    expected: list[str],
) -> None:
    """本文の直コミットを断る種類を記載の順に返却する（正常系）。"""
    # 準備（端末の設定の sources[].direct_commit は持たない配信元）
    env = make_view_env(direct_commit=direct_commit)
    # 実行
    response = get_source_config(_target(env), store=env.handlers.store)
    # 検証
    assert response.direct_commit.metadata_only_kinds == expected
    assert response.model_dump(by_alias=True)["directCommit"] == {"metadataOnlyKinds": expected}


def test_get_source_config_when_schemas(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """行ごとの種類のスキーマを返す（正常系）。"""
    # 準備（起動時に読んだ種類のスキーマを持つ配信元）
    env = make_view_env(
        SCHEMA_FILES,
        tables=SCHEMA_TABLES,
        schemas={
            "design": {
                "type": "object",
                "properties": {"title": {"$ref": "#/$defs/title"}},
                "$defs": {"title": {"type": "string"}},
            },
            "files_guide": {
                "type": "object",
                "properties": {"files": {"type": "array", "items": {"required": ["path"]}}},
            },
        },
    )
    target = _target(env)
    # 実行
    response = get_source_config(target, store=env.handlers.store, schemas=True)
    # 検証
    assert response.schemas is not None
    assert list(response.schemas) == ["design", "files_guide"]
    assert response.schemas["design"] == env.handlers.store.row_schema(target, "design")
    assert response.schemas["design"]["properties"]["title"] == {"type": "string"}
    assert response.schemas["files_guide"] == env.handlers.store.row_schema(target, "files_guide")


def test_list_documents(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """行の順に並べる（正常系）。"""
    # 準備
    env = make_view_env(NOTES_FILES, tables=NOTES_TABLES)
    target = _target(env)
    versions = [found.version for found in env.handlers.store.load(target).documents]
    # 実行
    response = list_documents(target, store=env.handlers.store)
    # 検証
    assert [item.kind for item in response.documents] == ["rules", "notes"]
    assert response.documents[0].body_path is None
    assert response.documents[1].body_path == "notes/guide.md"
    assert [item.version for item in response.documents] == versions
    assert response.documents[0].value is None
    assert response.documents[1].value is None
    assert response.documents[0].common_keys is None
    assert response.documents[1].common_keys is None


def test_list_documents_when_values(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """値を求めたときだけ値を入れる（正常系）。"""
    # 準備
    env = make_view_env(NOTES_FILES, tables=NOTES_TABLES)
    # 実行
    response = list_documents(_target(env), store=env.handlers.store, values=True)
    # 検証
    assert response.documents[0].value == {"id": "a", "name": "A"}
    assert response.documents[1].value == {"path": "guide.md"}


def test_list_documents_when_common_keys(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """共通のキーを求めたときだけ文書の metadata を入れる（正常系）。"""
    # 準備
    env = make_view_env(LINKS_FILES, tables=LINKS_TABLES)
    target = _target(env)
    metadata = env.handlers.store.load(target).documents[0].metadata
    # 実行
    response = list_documents(target, store=env.handlers.store, common_keys=True)
    # 検証
    item = response.documents[0]
    assert item.common_keys == metadata
    assert item.common_keys is not None
    assert item.common_keys["related"] == [{"to": "D-2"}]
    assert item.common_keys["alias_type"] == "term"
    assert item.value is None


ASSET_TABLES = [
    DocumentTable(
        id="assets",
        paths=["assets/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        metadata={"status": "state"},
        search_exclude={"field": "status", "op": "eq", "values": ["inactive"]},
    ),
    DocumentTable(id="design", paths=["docs/*.yaml"], schema_path="schemas/rule.schema.yaml"),
]
ASSET_FILES = {
    "schemas/rule.schema.yaml": "type: object\n",
    "assets/a1.yaml": "id: a1\nname: A1\nstate: active\n",
    "assets/a2.yaml": "id: a2\nname: A2\nstate: inactive\n",
    "docs/a.yaml": "id: a\nname: A\n",
}


def test_list_documents_when_search_excluded(
    make_view_env: Callable[..., SimpleNamespace],
) -> None:
    """除く条件に該当する文書も並べて excluded を付ける（正常系）。"""
    # 準備
    env = make_view_env(ASSET_FILES, tables=ASSET_TABLES)
    # 実行
    response = list_documents(_target(env), store=env.handlers.store)
    # 検証
    assert [item.id for item in response.documents] == ["a1", "a2", "a"]
    assert [item.excluded for item in response.documents] == [False, True, False]


def test_list_documents_when_ref_and_search_excluded(
    make_view_env: Callable[..., SimpleNamespace], monkeypatch: pytest.MonkeyPatch
) -> None:
    """リビジョンを指しても書き出さずに excluded を付ける（正常系）。"""
    # 準備
    env = make_view_env(ASSET_FILES, tables=ASSET_TABLES)
    store = env.handlers.store
    startup = _target(env)
    loaded = store.load(startup)
    target = dataclasses.replace(startup, ref="main")

    def _load(*_args: object, **_kwargs: object) -> object:
        return loaded

    monkeypatch.setattr(store, "load", _load)

    def _checkout(*_args: object, **_kwargs: object) -> object:
        msg = "リビジョンを書き出した"
        raise AssertionError(msg)

    monkeypatch.setattr(store.snapshots, "checkout", _checkout)
    # 実行
    response = list_documents(target, store=store)
    # 検証
    assert [item.excluded for item in response.documents] == [False, True, False]


def test_get_document(
    make_view_env: Callable[..., SimpleNamespace], monkeypatch: pytest.MonkeyPatch
) -> None:
    """値とスキーマを返し、変換しない（正常系）。"""
    # 準備（起動時に読んだ種類のスキーマを持つ配信元）
    env = make_view_env(NOTES_FILES, tables=NOTES_TABLES, schemas={"rules": {"type": "object"}})
    calls: list[object] = []

    def record(*args: object) -> None:
        calls.append(args)

    monkeypatch.setattr(env.handlers.converter, "convert", record)
    # 実行
    response = get_document(
        _target(env), "docs/a.yaml", store=env.handlers.store, converter=env.handlers.converter
    )
    # 検証
    assert response.value == {"id": "a", "name": "A"}
    assert response.model_dump(by_alias=True)["schema"] == {"type": "object"}
    assert response.metadata is not None
    assert response.metadata.common_keys == {"id": "a", "name": "A"}
    assert response.markdown is None
    assert calls == []


def test_get_document_item_versions(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """最上位のキーごとのバージョンを返却する（正常系）。"""
    # 準備
    files = {
        "schemas/rule.schema.yaml": "type: object\n",
        "docs/a.yaml": "id: a\ntitle: タイトル\ndescription: 説明\n",
    }
    env = make_view_env(files, tables=NOTES_TABLES[:1], schemas={"rules": {"type": "object"}})
    # 実行
    response = get_document(
        _target(env), "docs/a.yaml", store=env.handlers.store, converter=env.handlers.converter
    )
    # 検証
    assert response.item_versions == {
        "id": value_hash("a"),
        "title": value_hash("タイトル"),
        "description": value_hash("説明"),
    }


def test_get_document_when_body_path(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """本文のファイルのパスで引く（正常系）。"""
    # 準備
    env = make_view_env(NOTES_FILES, tables=NOTES_TABLES)
    # 実行
    response = get_document(
        _target(env), "notes/guide.md", store=env.handlers.store, converter=env.handlers.converter
    )
    # 検証
    assert response.value == {"path": "guide.md"}
    assert response.body == "# Guide\n"
    assert response.body_path == "notes/guide.md"


def test_get_document_when_doc_id(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """文書の ID で行の文書を選ぶ（正常系）。"""
    # 準備
    env = make_view_env(TERMS_FILES, tables=TERMS_TABLES)
    # 実行
    response = get_document(
        _target(env),
        "terms.yaml",
        doc_id="term-2",
        store=env.handlers.store,
        converter=env.handlers.converter,
    )
    # 検証
    assert response.value == {"id": "term-2", "name": "beta"}
    assert response.metadata is not None
    assert response.metadata.id == "term-2"


def test_get_document_when_converter(
    make_view_env: Callable[..., SimpleNamespace], monkeypatch: pytest.MonkeyPatch
) -> None:
    """converters[] を指す種類はスクリプトの Markdown を返す（正常系）。"""
    # 準備
    env = make_view_env(converters=[ScriptEntry(id="c", run=["python3", "scripts/c.py"])])

    def fake_convert(target: object, document: object) -> SimpleNamespace:
        return SimpleNamespace(markdown="# 変換した\n", failure=None)

    monkeypatch.setattr(env.handlers.converter, "convert", fake_convert)
    # 実行
    response = get_document(
        _target(env), "docs/a.yaml", store=env.handlers.store, converter=env.handlers.converter
    )
    # 検証
    assert response.markdown == "# 変換した\n"


def test_get_document_when_yaml_broken(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """YAML を読み込めない文書（正常系）。"""
    # 準備
    env = make_view_env({"docs/a.yaml": "a: [1\n"})
    # 実行
    response = get_document(
        _target(env), "docs/a.yaml", store=env.handlers.store, converter=env.handlers.converter
    )
    # 検証
    error = response.conversion_error
    assert response.value is None
    assert error is not None
    assert error.file == "docs/a.yaml"
    assert error.line is not None


def test_get_document_when_ref_and_no_dates(
    make_view_env: Callable[..., SimpleNamespace],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """日時を持たないリビジョンの文書を作業ツリーで stat しない（正常系）。"""
    # 準備（作業ツリーに design/D-9.yaml は無い）
    env = make_view_env(NOTES_FILES, tables=NOTES_TABLES, schemas={"rules": {"type": "object"}})
    target = dataclasses.replace(_target(env), ref="feature")
    document = make_document(id="D-9", path="design/D-9.yaml", data={"id": "D-9"}, updated=None)
    store = env.handlers.store

    def find_page(*_args: object, **_kwargs: object) -> Document:
        return document

    def row_schema(*_args: object) -> dict[str, object]:
        return {"type": "object"}

    def file_updated(*_args: object) -> datetime:
        return REVISION_TIME

    monkeypatch.setattr(store, "find_page", find_page)
    monkeypatch.setattr(store, "row_schema", row_schema)
    monkeypatch.setattr(store, "file_updated", file_updated)
    # 実行
    response = get_document(
        target, "design/D-9.yaml", store=store, converter=env.handlers.converter
    )
    # 検証
    assert response.updated_at == REVISION_TIME
    assert response.value == {"id": "D-9"}


def test_get_document_when_ref_and_yaml_broken(
    make_view_env: Callable[..., SimpleNamespace], monkeypatch: pytest.MonkeyPatch
) -> None:
    """リビジョンにだけある読み込めない YAML（正常系）。"""
    # 準備（作業ツリーに design/broken.yaml は無い）
    env = make_view_env(NOTES_FILES, tables=NOTES_TABLES, schemas={"rules": {"type": "object"}})
    target = dataclasses.replace(_target(env), ref="feature")
    problem = LoadProblem(
        path="design/broken.yaml", reason="unreadable", detail="broken", line=1, column=4
    )
    store = env.handlers.store

    def find_page(*_args: object, **_kwargs: object) -> None:
        return None

    def load(*_args: object, **_kwargs: object) -> LoadResult:
        return LoadResult(problems=[problem])

    def file_updated(*_args: object) -> datetime:
        return REVISION_TIME

    monkeypatch.setattr(store, "find_page", find_page)
    monkeypatch.setattr(store, "load", load)
    monkeypatch.setattr(store, "file_updated", file_updated)
    # 実行
    response = get_document(
        target, "design/broken.yaml", store=store, converter=env.handlers.converter
    )
    # 検証
    error = response.conversion_error
    assert error is not None
    assert (error.file, error.line, error.column) == ("design/broken.yaml", 1, 4)
    assert response.updated_at == REVISION_TIME


def test_get_document_when_not_found(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """無いパス（異常系）。"""
    # 準備
    env = make_view_env()
    # 実行・検証
    with pytest.raises(DocumentNotFoundError, match=r"no/such\.yaml"):
        get_document(
            _target(env), "no/such.yaml", store=env.handlers.store, converter=env.handlers.converter
        )


def test_list_decisions(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """フォルダの数を数える（正常系）。"""
    # 準備
    env = make_view_env(
        {
            "docs/a.yaml": "id: a\nname: A\n",
            "tmp/a/.mindstella/docs/D-1.md": "# D-1\n",
            "tmp/a/.mindstella/docs/D-2.md": "# D-2 a\n",
            "tmp/b/.mindstella/docs/D-2.md": "# D-2 b\n",
        },
        decision_folders=["tmp/a", "tmp/b"],
    )
    # 実行
    items = list_decisions(env.source)
    # 検証
    assert [(item.id, item.folders) for item in items] == [("D-1", 1), ("D-2", 2)]


def test_get_decision(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """1 つのフォルダにある文書を返す（正常系）。"""
    # 準備
    env = make_view_env(
        {"docs/a.yaml": "id: a\nname: A\n", "tmp/a/.mindstella/docs/D-1.md": "# D-1 の本文\n"},
        decision_folders=["tmp/a", "tmp/b"],
    )
    # 実行
    response = get_decision(env.source, "D-1")
    # 検証
    assert response.body == "# D-1 の本文\n"
    assert response.folder == "tmp/a"


def test_get_decision_when_ambiguous(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """2 つのフォルダにある（異常系）。"""
    # 準備
    env = make_view_env(
        {
            "docs/a.yaml": "id: a\nname: A\n",
            "tmp/a/.mindstella/docs/D-2.md": "# D-2 a\n",
            "tmp/b/.mindstella/docs/D-2.md": "# D-2 b\n",
        },
        decision_folders=["tmp/a", "tmp/b"],
    )
    # 実行・検証
    with pytest.raises(DecisionNotFoundError) as exc_info:
        get_decision(env.source, "D-2")
    assert exc_info.value.reason == "ambiguous"
    assert len(exc_info.value.folders) == 2


def test_get_decision_when_invalid_id(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """形式に当たらない ID（異常系）。"""
    # 準備
    env = make_view_env(decision_folders=["tmp/a"])
    # 実行・検証
    with pytest.raises(DecisionNotFoundError) as exc_info:
        get_decision(env.source, "../secret")
    assert exc_info.value.reason == "not_found"


def test_get_document_when_doc_id_not_found(
    make_view_env: Callable[..., SimpleNamespace],
) -> None:
    """文書の ID が一致しない（異常系）。"""
    # 準備
    env = make_view_env(TERMS_FILES, tables=TERMS_TABLES)
    target = _target(env)
    # 実行・検証
    with pytest.raises(DocumentNotFoundError, match=r"terms\.yaml"):
        get_document(
            target,
            "terms.yaml",
            doc_id="no-such",
            store=env.handlers.store,
            converter=env.handlers.converter,
        )


def test_get_document_when_sqlite_row(
    make_view_env: Callable[..., SimpleNamespace], make_notes_db: Callable[..., Path]
) -> None:
    """SQLite の行の文書の schema を列の説明から作る（正常系）。"""
    from project_index.features.documents.sqlite_rows import columns_schema

    # 準備
    table = notes_db_table()
    env = make_view_env(tables=[table])
    make_notes_db(env.root)
    # 実行
    response = get_document(
        _target(env),
        "data/notes.db",
        doc_id="n1",
        store=env.handlers.store,
        converter=env.handlers.converter,
    )
    # 検証
    assert response.value == {
        "id": "n1",
        "title": "ゲーム実況 1",
        "summary": "今日の目標 1",
        "tags": ["game"],
        "aliases": ["実況"],
    }
    assert response.model_dump(by_alias=True)["schema"] == columns_schema(table)

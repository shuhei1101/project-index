from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from project_index.features.access.types import Target
from project_index.features.read.paths import read_target
from project_index.features.read.service import (
    get_decision,
    get_document,
    get_source_config,
    list_decisions,
    list_documents,
)
from project_index.features.sources.types import DocumentTable, ScriptEntry
from project_index.shared.errors import DecisionNotFoundError, DocumentNotFoundError

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
    response = get_source_config(env.source)
    # 検証
    dumped = response.model_dump()
    assert dumped["nav"] == nav
    assert dumped["decisions"] == {"folders": ["tmp/a"]}
    assert [row["id"] for row in dumped["documents"]] == ["rules"]
    assert "converters" not in dumped
    assert "python3" not in str(dumped)


def test_get_source_config_when_no_decisions(
    make_view_env: Callable[..., SimpleNamespace],
) -> None:
    """decisions を持たない（正常系）。"""
    # 準備
    env = make_view_env()
    # 実行
    response = get_source_config(env.source)
    # 検証
    assert response.decisions == {"folders": []}


def test_list_documents(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """行の順に並べる（正常系）。"""
    # 準備
    env = make_view_env(NOTES_FILES, tables=NOTES_TABLES)
    # 実行
    response = list_documents(_target(env), store=env.handlers.store)
    # 検証
    assert [item.kind for item in response.documents] == ["rules", "notes"]
    assert response.documents[0].body_path is None
    assert response.documents[1].body_path == "notes/guide.md"


def test_get_document(
    make_view_env: Callable[..., SimpleNamespace], monkeypatch: pytest.MonkeyPatch
) -> None:
    """値とスキーマを返し、変換しない（正常系）。"""
    # 準備
    env = make_view_env(NOTES_FILES, tables=NOTES_TABLES)
    calls: list[object] = []
    monkeypatch.setattr(env.handlers.converter, "convert", lambda *args: calls.append(args))
    # 実行
    response = get_document(
        _target(env), "docs/a.yaml", store=env.handlers.store, converter=env.handlers.converter
    )
    # 検証
    assert response.value == {"id": "a", "name": "A"}
    assert response.model_dump(by_alias=True)["schema"] == {"type": "object"}
    assert response.markdown is None
    assert calls == []


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


def test_get_document_when_converter(
    make_view_env: Callable[..., SimpleNamespace], monkeypatch: pytest.MonkeyPatch
) -> None:
    """converters[] を指す種類はスクリプトの Markdown を返す（正常系）。"""
    # 準備
    env = make_view_env(converters=[ScriptEntry(id="c", run=["python3", "scripts/c.py"])])
    monkeypatch.setattr(
        env.handlers.converter,
        "convert",
        lambda target, document: SimpleNamespace(markdown="# 変換した\n", failure=None),
    )
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


def test_get_document_when_not_found(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """無いパス（異常系）。"""
    # 準備
    env = make_view_env()
    # 実行・検証
    with pytest.raises(DocumentNotFoundError, match="no/such.yaml"):
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

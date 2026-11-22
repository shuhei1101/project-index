from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

from project_index.features.documents import sqlite_rows as sqlite_rows_module
from project_index.features.documents.sqlite_rows import (
    SqliteRowCache,
    SqliteRows,
    columns_schema,
    file_signature,
    inspect_table,
    read_rows,
)
from project_index.features.sources.types import DocumentTable, SqliteColumn, SqliteTable

if TYPE_CHECKING:
    from pathlib import Path

    from project_index.features.documents.types import Document


def _create_notes(
    path: Path, rows: list[tuple[str, str, str, str, str, str]], *, wal: bool = False
) -> None:
    """テスト用の表 notes を作り、行を入れる。"""
    conn = sqlite3.connect(path)
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE notes (id TEXT, title TEXT, summary TEXT, tags TEXT, aliases TEXT, state TEXT)"
    )
    conn.executemany("INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _notes_table(**sqlite_overrides: object) -> DocumentTable:
    """表 notes を指す行を作る。"""
    columns = [
        SqliteColumn(name="id", description="ID"),
        SqliteColumn(name="title", description="タイトル"),
        SqliteColumn(name="summary", description="要約"),
        SqliteColumn(name="tags", type="json", description="タグ"),
        SqliteColumn(name="aliases", type="json", description="別名"),
        SqliteColumn(name="state", description="状態"),
    ]
    values: dict[str, object] = {"file": "data/notes.db", "table": "notes", "columns": columns}
    values.update(sqlite_overrides)
    return DocumentTable(
        id="notes_db",
        paths=[],
        schema_path=None,
        sqlite=SqliteTable(**values),  # pyright: ignore[reportArgumentType]
        metadata={"name": "title", "description": "summary"},
        alias_type="term",
    )


_N1 = ("n1", "ゲーム実況 1", "今日の目標 1", json.dumps(["game"]), json.dumps(["実況"]), "active")
_N2 = ("n2", "雑談 1", "今日の目標 2", json.dumps(["talk"]), json.dumps([]), "active")


def _ids(documents: list[Document]) -> list[str]:
    return [document.id for document in documents]


def test_file_signature_changes_with_wal(tmp_path: Path) -> None:
    """WAL への書き込みで署名が変わる（正常系）。"""
    # 準備
    db = tmp_path / "notes.db"
    _create_notes(db, [_N1], wal=True)
    writer = sqlite3.connect(db)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    before = file_signature(db)
    # 実行
    writer.execute("INSERT INTO notes VALUES ('n3', 't', 's', '[]', '[]', 'active')")
    writer.commit()
    after = file_signature(db)
    writer.close()
    # 検証
    assert before is not None
    assert after is not None
    assert before != after


def test_file_signature_when_missing(tmp_path: Path) -> None:
    """ファイルが無ければ None（正常系）。"""
    # 準備
    db = tmp_path / "missing.db"
    # 実行
    result = file_signature(db)
    # 検証
    assert result is None


def test_read_rows(tmp_path: Path) -> None:
    """行を文書にし、共通のメタデータと json の列を読む（正常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    _create_notes(tmp_path / "data/notes.db", [_N2, _N1])
    table = _notes_table()
    # 実行
    result = read_rows(tmp_path, "sample", table)
    # 検証
    assert _ids(result.documents) == ["n1", "n2"]
    n1 = result.documents[0]
    assert n1.kind == "notes_db"
    assert n1.source_id == "sample"
    assert n1.path == "data/notes.db"
    assert n1.metadata["name"] == "ゲーム実況 1"
    assert n1.metadata["description"] == "今日の目標 1"
    assert n1.metadata["tags"] == ["game"]
    assert n1.metadata["aliases"] == ["実況"]
    assert n1.metadata["alias_type"] == "term"
    assert n1.data["tags"] == ["game"]
    assert result.omitted == 0
    assert result.warnings == []
    assert result.signature is not None


def test_read_rows_when_over_limit(tmp_path: Path) -> None:
    """上限を超えた分は配信せずに数える（正常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    _create_notes(
        tmp_path / "data/notes.db",
        [
            ("a", "b-title", "s", "[]", "[]", "active"),
            ("b", "c-title", "s", "[]", "[]", "active"),
            ("c", "a-title", "s", "[]", "[]", "active"),
            ("d", "z-title", "s", "[]", "[]", "closed"),
        ],
    )
    table = _notes_table(where="state != 'closed'", order_by="title DESC", limit=2)
    # 実行
    result = read_rows(tmp_path, "sample", table)
    # 検証
    assert _ids(result.documents) == ["b", "a"]
    assert result.omitted == 1


def test_read_rows_when_integer_id(tmp_path: Path) -> None:
    """整数の id の列を文字列の ID にする（正常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    conn = sqlite3.connect(tmp_path / "data/notes.db")
    conn.execute("CREATE TABLE notice (id INTEGER PRIMARY KEY, title TEXT)")
    conn.executemany("INSERT INTO notice VALUES (?, ?)", [(1, "a"), (2, "b")])
    conn.commit()
    conn.close()
    table = DocumentTable(
        id="notice",
        paths=[],
        schema_path=None,
        sqlite=SqliteTable(
            file="data/notes.db",
            table="notice",
            columns=[
                SqliteColumn(name="id", type="integer", description="ID"),
                SqliteColumn(name="title", description="タイトル"),
            ],
        ),
        metadata={"name": "title"},
    )
    # 実行
    result = read_rows(tmp_path, "sample", table)
    # 検証
    assert _ids(result.documents) == ["1", "2"]


def test_read_rows_when_duplicate_id(tmp_path: Path) -> None:
    """重なる ID は最初の行だけを残す（正常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    _create_notes(tmp_path / "data/notes.db", [_N1, ("n1", "別の行", "s", "[]", "[]", "active")])
    table = _notes_table()
    # 実行
    result = read_rows(tmp_path, "sample", table)
    # 検証
    assert _ids(result.documents) == ["n1"]
    assert result.documents[0].metadata["name"] == "ゲーム実況 1"
    assert len(result.warnings) == 1
    assert "n1" in result.warnings[0]


def test_read_rows_when_bad_json(tmp_path: Path) -> None:
    """JSON として読めない値は空にする（正常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    _create_notes(tmp_path / "data/notes.db", [("n1", "t", "s", "not json", "[]", "active")])
    table = _notes_table()
    # 実行
    result = read_rows(tmp_path, "sample", table)
    # 検証
    assert result.documents[0].data["tags"] is None
    assert len(result.warnings) == 1
    assert "n1" in result.warnings[0]
    assert "tags" in result.warnings[0]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(None, id="missing"),
        pytest.param(b"not a sqlite file", id="not_sqlite"),
    ],
)
def test_read_rows_when_unopenable(tmp_path: Path, content: bytes | None) -> None:
    """開けないファイルは警告で返す（異常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    db = tmp_path / "data/notes.db"
    if content is not None:
        db.write_bytes(content)
    table = _notes_table()
    # 実行
    result = read_rows(tmp_path, "sample", table)
    # 検証
    assert result.documents == []
    assert len(result.warnings) == 1
    assert result.signature is None
    assert db.exists() is (content is not None)


def test_read_rows_read_only(tmp_path: Path) -> None:
    """書き込みの文を where に入れても書き込まない（正常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    db = tmp_path / "data/notes.db"
    _create_notes(db, [_N1, _N2])
    before = db.read_bytes()
    table = _notes_table(where="1=1; DELETE FROM notes")
    # 実行
    result = read_rows(tmp_path, "sample", table)
    # 検証
    assert result.documents == []
    assert len(result.warnings) == 1
    assert db.read_bytes() == before


def test_rows_reuse_when_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ファイルが変わらなければ読み直さない（正常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    _create_notes(tmp_path / "data/notes.db", [_N1])
    calls: list[str] = []
    original = sqlite_rows_module.read_rows

    def counting(source_root: Path, source_id: str, table: DocumentTable) -> SqliteRows:
        calls.append(table.id)
        return original(source_root, source_id, table)

    monkeypatch.setattr(sqlite_rows_module, "read_rows", counting)
    cache = SqliteRowCache()
    table = _notes_table()
    # 実行
    first = cache.rows(tmp_path, "sample", table)
    second = cache.rows(tmp_path, "sample", table)
    # 検証
    assert calls == ["notes_db"]
    assert _ids(first.documents) == ["n1"]
    assert _ids(second.documents) == ["n1"]


@pytest.mark.parametrize("wal", [pytest.param(False, id="rollback"), pytest.param(True, id="wal")])
def test_rows_reload_when_changed(tmp_path: Path, wal: bool) -> None:
    """行を書き換えた後は読み直す（正常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    db = tmp_path / "data/notes.db"
    _create_notes(db, [_N1], wal=wal)
    cache = SqliteRowCache()
    table = _notes_table()
    first = cache.rows(tmp_path, "sample", table)
    writer = sqlite3.connect(db)
    writer.execute("UPDATE notes SET title = '書き換えた' WHERE id = 'n1'")
    writer.execute("INSERT INTO notes VALUES ('n3', 't3', 's3', '[]', '[]', 'active')")
    writer.commit()
    writer.close()
    # 実行
    second = cache.rows(tmp_path, "sample", table)
    # 検証
    assert _ids(second.documents) == ["n1", "n3"]
    assert second.documents[0].metadata["name"] == "書き換えた"
    assert second.documents[0].version != first.documents[0].version


def test_rows_reload_when_definition_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """署名が同じでも行の定義が違えば読み直す（正常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    _create_notes(tmp_path / "data/notes.db", [_N1, _N2])
    calls: list[str | None] = []
    original = sqlite_rows_module.read_rows

    def counting(source_root: Path, source_id: str, table: DocumentTable) -> SqliteRows:
        calls.append(table.sqlite.where if table.sqlite else None)
        return original(source_root, source_id, table)

    monkeypatch.setattr(sqlite_rows_module, "read_rows", counting)
    cache = SqliteRowCache()
    game = _notes_table(where="id = 'n1'")
    talk = _notes_table(where="id = 'n2'")
    # 実行
    results = [
        cache.rows(tmp_path, "sample", game),
        cache.rows(tmp_path, "sample", talk),
        cache.rows(tmp_path, "sample", game),
        cache.rows(tmp_path, "sample", talk),
    ]
    # 検証
    assert calls == ["id = 'n1'", "id = 'n2'"]
    assert [_ids(result.documents) for result in results] == [["n1"], ["n2"], ["n1"], ["n2"]]


def test_rows_when_file_appears(tmp_path: Path) -> None:
    """開けなかったファイルを配置した後は読む（正常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    cache = SqliteRowCache()
    table = _notes_table()
    first = cache.rows(tmp_path, "sample", table)
    _create_notes(tmp_path / "data/notes.db", [_N1])
    # 実行
    second = cache.rows(tmp_path, "sample", table)
    # 検証
    assert first.documents == []
    assert len(first.warnings) == 1
    assert _ids(second.documents) == ["n1"]


def test_inspect_table_violations(tmp_path: Path) -> None:
    """ファイル・表・列の欠けを違反にする（異常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    _create_notes(tmp_path / "data/notes.db", [_N1])
    missing_file = _notes_table(file="data/missing.db")
    missing_table = _notes_table(table="memos")
    missing_column = DocumentTable(
        id="notes_db",
        paths=[],
        schema_path=None,
        sqlite=SqliteTable(
            file="data/notes.db",
            table="notes",
            columns=[
                SqliteColumn(name="id", description="ID"),
                SqliteColumn(name="title", description="タイトル"),
            ],
        ),
        metadata={"name": "heading"},
    )
    # 実行
    file_result = inspect_table(tmp_path, missing_file, 2)
    table_result = inspect_table(tmp_path, missing_table, 3)
    column_result = inspect_table(tmp_path, missing_column, 4)
    # 検証
    assert [v.path for v in file_result[0]] == ["documents[2].sqlite.file"]
    assert [v.path for v in table_result[0]] == ["documents[3].sqlite.table"]
    assert [v.path for v in column_result[0]] == ["documents[4].metadata.name"]


def test_inspect_table_warnings(tmp_path: Path) -> None:
    """上限を超えた行の数を警告にする（正常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    _create_notes(tmp_path / "data/notes.db", [_N1, _N2])
    table = _notes_table(limit=1)
    # 実行
    violations, warnings = inspect_table(tmp_path, table, 0)
    # 検証
    assert violations == []
    assert len(warnings) == 1
    assert warnings[0].path == "documents[0].sqlite.limit"
    assert "1" in warnings[0].rule


def test_columns_schema() -> None:
    """列の並びと型と説明を写す（正常系）。"""
    # 準備
    table = DocumentTable(
        id="t",
        paths=[],
        schema_path=None,
        sqlite=SqliteTable(
            file="x.db",
            table="t",
            columns=[
                SqliteColumn(name="id", description="ID"),
                SqliteColumn(name="count", type="integer", description="回数"),
                SqliteColumn(name="tags", type="json", description="タグ"),
            ],
        ),
    )
    # 実行
    result = columns_schema(table)
    # 検証
    assert result == {
        "type": "object",
        "properties": {
            "id": {"title": "ID", "type": "string"},
            "count": {"title": "回数", "type": "integer"},
            "tags": {"title": "タグ"},
        },
    }


def _no_id_table() -> DocumentTable:
    """`metadata` に `id` を書かず、列 `id` を `columns[]` に持たない行を作る。"""
    return DocumentTable(
        id="notes_db",
        paths=[],
        schema_path=None,
        sqlite=SqliteTable(
            file="data/notes.db",
            table="notes",
            columns=[SqliteColumn(name="title", description="タイトル")],
        ),
        metadata={"name": "title"},
    )


def test_inspect_table_when_id_column_missing(tmp_path: Path) -> None:
    """id に対応する列が columns[] に無い行を違反にする（異常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    _create_notes(tmp_path / "data/notes.db", [_N1])
    table = _no_id_table()
    # 実行
    violations, warnings = inspect_table(tmp_path, table, 0)
    # 検証
    assert [v.path for v in violations] == ["documents[0].sqlite.columns"]
    assert "id" in violations[0].rule
    assert warnings == []


def test_read_rows_when_id_column_missing(tmp_path: Path) -> None:
    """id に対応する列が columns[] に無い行は、例外を送出せず警告で返す（異常系）。"""
    # 準備
    (tmp_path / "data").mkdir()
    _create_notes(tmp_path / "data/notes.db", [_N1])
    table = _no_id_table()
    # 実行
    result = read_rows(tmp_path, "sample", table)
    # 検証
    assert result.documents == []
    assert len(result.warnings) == 1
    assert "id" in result.warnings[0]

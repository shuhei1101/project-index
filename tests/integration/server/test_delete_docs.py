from __future__ import annotations

from typing import TYPE_CHECKING, Any

from project_index.shared.hashing import content_hash
from project_index.shared.yaml_io import load_yaml as load_yaml_value

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def load_yaml(text: str) -> Any:
    """形の分かっている YAML の文字列を読む。"""
    return load_yaml_value(text)


REFERENCING = {"to": "doc-2", "type": "references"}
WRITABLE_FALSE_ROW = (
    "  - id: sample\n"
    "    paths: [docs/*.yaml]\n"
    "    schema: schemas/sample.schema.yaml\n"
    "    writable: false\n"
)


def _version(path: Path) -> str:
    """文書のファイルの今のバージョン（内容のハッシュ）を返す。"""
    return content_hash(path.read_text(encoding="utf-8"))


def _setup(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    files: dict[str, str] | None = None,
) -> tuple[Any, Any, Path]:
    """ワークツリー x を持つ sample を起動し、配信元・環境・ワークツリーを返す。"""
    source = make_source("sample", files)
    worktree = add_worktree(source.folder, "x")
    return source, make_server(source), worktree


def _referenced_files(
    sample_file_set: Callable[..., dict[str, str]], sample_doc_text: Callable[..., str]
) -> dict[str, str]:
    """文書 1 の related が文書 2 を指す、配信元のファイル一式を返す。"""
    return sample_file_set(
        **{"docs/doc-1.yaml": sample_doc_text("doc-1", "文書 1", related=[REFERENCING])}
    )


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
) -> None:
    """参照されていない文書をワークツリーから消す（正常系）。"""
    # 準備
    source, env, worktree = _setup(make_source, make_server, add_worktree)
    target = worktree / "docs" / "doc-2.yaml"
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        targets=[{"id": "doc-2", "expected_version": _version(target)}],
    )
    found = env.call(
        "search_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        view="ids",
        format="json",
    )
    # 検証
    assert not result.is_error
    assert result.data["applied"] is True
    assert result.data["results"][0]["status"] == "deleted"
    assert not target.exists()
    assert (source.folder / "docs" / "doc-2.yaml").is_file()
    assert "doc-2" not in found.text
    assert "doc-1" in found.text


def test_normal_when_unlink(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """on_referenced: unlink で参照元の related から外して消す（正常系）。"""
    # 準備
    files = _referenced_files(sample_file_set, sample_doc_text)
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    target = worktree / "docs" / "doc-2.yaml"
    referrer = worktree / "docs" / "doc-1.yaml"
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        targets=[{"id": "doc-2", "expected_version": _version(target)}],
        on_referenced="unlink",
    )
    # 検証
    assert not target.exists()
    assert not load_yaml(referrer.read_text(encoding="utf-8")).get("related")
    assert result.data["unlinked"] == [{"id": "doc-1", "version": _version(referrer)}]


def test_normal_when_dry_run(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """dry_run: true で消した場合の結果だけを返す（正常系）。"""
    # 準備
    files = _referenced_files(sample_file_set, sample_doc_text)
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    target = worktree / "docs" / "doc-2.yaml"
    referrer = worktree / "docs" / "doc-1.yaml"
    before = (target.read_text(encoding="utf-8"), referrer.read_text(encoding="utf-8"))
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        targets=[{"id": "doc-2", "expected_version": _version(target)}],
        on_referenced="unlink",
        dry_run=True,
    )
    # 検証
    assert result.data["applied"] is False
    assert result.data["results"][0]["id"] == "doc-2"
    assert result.data["unlinked"][0]["id"] == "doc-1"
    assert (target.read_text(encoding="utf-8"), referrer.read_text(encoding="utf-8")) == before


def test_error_when_referenced(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """参照されている文書を on_referenced: fail で消すと断る（異常系）。"""
    # 準備
    files = _referenced_files(sample_file_set, sample_doc_text)
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    target = worktree / "docs" / "doc-2.yaml"
    referrer = worktree / "docs" / "doc-1.yaml"
    before = (target.read_text(encoding="utf-8"), referrer.read_text(encoding="utf-8"))
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        targets=[{"id": "doc-2", "expected_version": _version(target)}],
    )
    # 検証
    assert result.is_error
    assert "DocumentReferencedError" in result.text
    assert "doc-1" in result.text
    assert "unlink" in result.text
    assert (target.read_text(encoding="utf-8"), referrer.read_text(encoding="utf-8")) == before


def test_error_when_version_mismatch(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_doc_text: Callable[..., str],
) -> None:
    """読んだ後に直接編集された文書を消さない（異常系）。"""
    # 準備
    source, env, worktree = _setup(make_source, make_server, add_worktree)
    target = worktree / "docs" / "doc-2.yaml"
    read_version = _version(target)
    edited = sample_doc_text("doc-2", "文書 2", description="直接編集した概要文")
    target.write_text(edited, encoding="utf-8")
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        targets=[{"id": "doc-2", "expected_version": read_version}],
    )
    # 検証
    assert result.is_error
    assert "VersionMismatchError" in result.text
    assert content_hash(edited) in result.text
    assert target.is_file()


def test_error_when_source_not_writable(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """scope.write に当たらない作業場所からの削除を断る（異常系）。"""
    # 準備
    sample = make_source("sample")
    notes = make_source("notes", git=False, scope_read=[sample.folder])
    env = make_server(sample, notes)
    target = notes.folder / "docs" / "doc-2.yaml"
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(sample.folder),
        source="notes",
        targets=[{"id": "doc-2", "expected_version": _version(target)}],
    )
    # 検証
    assert result.is_error
    assert "SourceNotWritableError" in result.text
    assert "notes" in result.text
    assert "sample" in result.text
    assert target.is_file()


def test_error_when_target_is_clone(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
) -> None:
    """Git の配信元のクローン本体からは消さない（異常系）。"""
    # 準備
    source, env, _ = _setup(make_source, make_server, add_worktree)
    target = source.folder / "docs" / "doc-2.yaml"
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(source.folder),
        targets=[{"id": "doc-2", "expected_version": _version(target)}],
    )
    # 検証
    assert result.is_error
    assert "TargetIsCloneError" in result.text
    assert "worktree" in result.text
    assert target.is_file()


def test_error_when_delete_not_allowed(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """Git 管理外の配信元で writable が削除を許さない種類の文書を消さない（異常系）。"""
    # 準備
    sample = make_source("sample")
    config = sample_config_text().replace(
        "  - id: sample\n    paths: [docs/*.yaml]\n    schema: schemas/sample.schema.yaml\n",
        WRITABLE_FALSE_ROW,
    )
    memo = make_source(
        "memo",
        sample_file_set(**{"project-index.yaml": config}),
        git=False,
        scope_read=[sample.folder],
        scope_write=[sample.folder],
    )
    env = make_server(sample, memo)
    target = memo.folder / "docs" / "doc-2.yaml"
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(sample.folder),
        source="memo",
        targets=[{"id": "doc-2", "expected_version": _version(target)}],
    )
    # 検証
    assert result.is_error
    assert "DeleteNotAllowedError" in result.text
    assert "sample" in result.text
    assert "writable" in result.text
    assert target.is_file()


def test_error_when_document_not_found(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
) -> None:
    """無い id の削除を断る（異常系）。"""
    # 準備
    source, env, worktree = _setup(make_source, make_server, add_worktree)
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        targets=[{"id": "doc-9", "expected_version": "000000"}],
    )
    # 検証
    assert result.is_error
    assert "DocumentNotFoundError" in result.text
    assert "doc-9" in result.text
    assert "doc-1" in result.text


# 単一引用符・`: ` を含む二重引用符の値を持ち、`related` が文書 2 を指す文書 1
QUOTED_REFERRER = (
    "id: doc-1\n"
    'name: "A: b"\n'
    "description: '2020-12'\n"
    "related:\n"
    "  - to: doc-2\n"
    "    type: references\n"
)


def test_normal_when_unlink_quotes_preserved(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """参照を外した参照元の文書の、変更していない項目の引用符の種類を元のまま書き出す（正常系）。"""
    # 準備
    files = sample_file_set(**{"docs/doc-1.yaml": QUOTED_REFERRER})
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    target = worktree / "docs" / "doc-2.yaml"
    referrer = worktree / "docs" / "doc-1.yaml"
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        targets=[{"id": "doc-2", "expected_version": _version(target)}],
        on_referenced="unlink",
    )
    # 検証
    assert not result.is_error
    assert referrer.read_text(encoding="utf-8").startswith(
        "id: doc-1\nname: \"A: b\"\ndescription: '2020-12'\n"
    )

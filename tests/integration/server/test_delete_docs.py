from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from project_index.shared.hashing import content_hash, value_hash
from project_index.shared.yaml_io import load_yaml as load_yaml_value

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.integration.server.conftest import DirectCommitSource


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
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    make_builtin_clone: Callable[[], Path],
) -> None:
    """scope.write に当たらない作業場所からの削除を断る（異常系）。"""
    # 準備
    sample = make_source("sample")
    notes = make_source("notes", git=False, scope_read=[sample.folder])
    clone = make_builtin_clone()
    env = make_server(sample, notes)
    target = notes.folder / "docs" / "doc-2.yaml"
    page = clone / "docs" / "guide" / "配信元を登録する.md"
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(sample.folder),
        source="notes",
        targets=[{"id": "doc-2", "expected_version": _version(target)}],
    )
    builtin = env.call(
        "delete_docs",
        cwd=str(clone),
        source="project-index",
        targets=[{"id": "docs/guide/配信元を登録する.md", "expected_version": "0000000"}],
    )
    # 検証
    assert result.is_error
    assert "SourceNotWritableError" in result.text
    assert "notes" in result.text
    assert "sample" in result.text
    assert target.is_file()
    assert builtin.is_error
    assert "SourceNotWritableError" in builtin.text
    assert page.is_file()


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


NOTES_ROW = (
    "  - id: notes\n"
    "    paths: [notes/index.yaml]\n"
    "    schema: schemas/notes.schema.yaml\n"
    "    records: items\n"
    "    body_file: path\n"
)
NOTES_SCHEMA = (
    "type: object\n"
    "properties:\n"
    "  items:\n"
    "    type: array\n"
    "    items:\n"
    "      type: object\n"
    "      properties:\n"
    "        id: {type: string}\n"
    "        path: {type: string}\n"
)
NOTES = (
    "items:\n"
    "  - id: n1\n    path: n1.md\n"
    "  - id: n2\n    path: n2.md\n"
    "  - id: n3\n    path: n1.md\n"
)


def test_normal_when_body_file(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """`records`・`body_file` の行の文書を、要素と本文のファイルごと削除する（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(NOTES_ROW),
            "schemas/notes.schema.yaml": NOTES_SCHEMA,
            "notes/index.yaml": NOTES,
            "notes/n1.md": "# n1\n",
            "notes/n2.md": "# n2\n",
        }
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    common = {"cwd": str(source.folder), "worktree": str(worktree)}
    # 実行
    first = env.call(
        "delete_docs",
        **common,
        targets=[
            {"id": "n2", "expected_version": value_hash([{"id": "n2", "path": "n2.md"}, "# n2\n"])}
        ],
    )
    second = env.call(
        "delete_docs",
        **common,
        targets=[
            {"id": "n3", "expected_version": value_hash([{"id": "n3", "path": "n1.md"}, "# n1\n"])}
        ],
    )
    checked = env.call_admin("check_project", path=str(worktree), format="json")
    # 検証
    assert not first.is_error
    assert not second.is_error
    assert load_yaml((worktree / "notes" / "index.yaml").read_text(encoding="utf-8")) == {
        "items": [{"id": "n1", "path": "n1.md"}]
    }
    assert not (worktree / "notes" / "n2.md").exists()
    assert (worktree / "notes" / "n1.md").read_text(encoding="utf-8") == "# n1\n"
    assert "notes/n2.md" not in checked.text


def test_normal_when_body_file_absent(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """`body_file` の列を持たない要素を、管理用の YAML の要素だけを除いて削除する（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(NOTES_ROW),
            "schemas/notes.schema.yaml": NOTES_SCHEMA,
            "notes/index.yaml": "items:\n  - id: n1\n    path: n1.md\n  - id: n4\n",
            "notes/n1.md": "# n1\n",
        }
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        targets=[{"id": "n4", "expected_version": value_hash({"id": "n4"})}],
    )
    # 検証
    assert not result.is_error
    assert result.data["results"][0]["status"] == "deleted"
    assert load_yaml((worktree / "notes" / "index.yaml").read_text(encoding="utf-8")) == {
        "items": [{"id": "n1", "path": "n1.md"}]
    }
    assert (worktree / "notes" / "n1.md").read_text(encoding="utf-8") == "# n1\n"


def test_error_when_disk_storage_delete_not_allowed(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """disk の配信元で writable が削除を許さない種類の文書を消さない（異常系）。"""
    # 準備
    config = sample_config_text(name="company").replace(
        "  - id: sample\n    paths: [docs/*.yaml]\n    schema: schemas/sample.schema.yaml\n",
        WRITABLE_FALSE_ROW,
    )
    company = make_source(
        "company", sample_file_set(**{"project-index.yaml": config}), storage="disk"
    )
    env = make_server(company)
    target = company.folder / "docs" / "doc-2.yaml"
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(company.folder),
        source="company",
        targets=[{"id": "doc-2", "expected_version": _version(target)}],
    )
    # 検証
    assert result.is_error
    assert "DeleteNotAllowedError" in result.text
    assert "TargetIsCloneError" not in result.text
    assert "writable" in result.text
    assert target.is_file()


# 最上位の refs と functions[0].refs を持つ n1
NESTED_N1 = (
    "id: n1\nname: n1\nrefs:\n  - {to: n2, type: references}\n"
    "  - {to: n3, type: references}\nfunctions:\n  - name: f\n"
    "    refs:\n      - {to: n2, type: references}\n"
)


def test_normal_when_unlink_nested_related(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    nested_file_set: Callable[..., dict[str, str]],
) -> None:
    """on_referenced: unlink が最上位と入れ子の refs の両方から参照を外す（正常系）。"""
    # 準備
    files = nested_file_set(NESTED_N1)
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    target = worktree / "nested" / "n2.yaml"
    referrer = worktree / "nested" / "n1.yaml"
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        targets=[{"id": "n2", "expected_version": _version(target)}],
        on_referenced="unlink",
    )
    # 検証
    data = load_yaml(referrer.read_text(encoding="utf-8"))
    assert not target.exists()
    assert data["refs"] == [{"to": "n3", "type": "references"}]
    assert data["functions"][0]["refs"] == []
    assert result.data["unlinked"] == [{"id": "n1", "version": _version(referrer)}]


def test_normal_when_direct_commit(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """直コミットで文書を消す（正常系）。"""
    # 準備
    direct = make_direct_commit_source(
        files={"notes/n1.yaml": "id: n1\nname: メモ 1\n", "generated/notes.txt": "n1\n"}
    )
    env = make_server(direct.spec)
    note = direct.develop / "notes" / "n1.yaml"
    remote_before = run_git(direct.bare, "rev-parse", "develop").strip()
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(direct.local),
        source="sample",
        targets=[{"id": "n1", "expected_version": content_hash(note.read_text(encoding="utf-8"))}],
        commit={"message": "docs: note を消す"},
    )
    # 検証
    data = result.data
    remote_after = run_git(direct.bare, "rev-parse", "develop").strip()
    changed = run_git(direct.bare, "show", "--name-only", "--format=", remote_after).split()
    assert not result.is_error, result.text
    assert data["applied"] is True
    assert data["results"][0]["status"] == "deleted"
    assert data["commit"]["branch"] == "develop"
    assert data["commit"]["sha"] == remote_after
    assert run_git(direct.bare, "rev-parse", f"{remote_after}~1").strip() == remote_before
    assert sorted(changed) == ["generated/notes.txt", "notes/n1.yaml"]
    assert not note.exists()
    assert run_git(direct.develop, "status", "--porcelain").strip() == ""


def test_error_when_direct_commit_body_delete_not_allowed(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """本文の直コミットを断る種類の本文のファイルを削除する（異常系）。"""
    from tests.integration.server.conftest import (
        F1_BODY,
        FILES_INDEX,
        METADATA_ONLY_FILES,
        metadata_only_config,
    )

    # 準備
    direct = make_direct_commit_source(config=metadata_only_config(), files=METADATA_ONLY_FILES)
    env = make_server(direct.spec)
    remote_before = run_git(direct.bare, "rev-parse", "develop").strip()
    version = value_hash([{"id": "f1", "name": "案内", "path": "f1.md"}, F1_BODY])
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(direct.local),
        source="sample",
        targets=[{"id": "f1", "expected_version": version}],
        commit={"message": "docs: files を消す"},
    )
    # 検証
    assert result.is_error
    assert "ValidationFailedError" in result.text
    assert "種類 files は本文の直コミットを断っている" in result.text
    assert run_git(direct.bare, "rev-parse", "develop").strip() == remote_before
    assert (direct.develop / "files" / "f1.md").read_text(encoding="utf-8") == F1_BODY
    assert (direct.develop / "files" / "index.yaml").read_text(encoding="utf-8") == FILES_INDEX
    assert run_git(direct.develop, "status", "--porcelain").strip() == ""


def test_error_when_direct_commit_kind_not_allowed(
    make_direct_commit_source: Callable[..., DirectCommitSource],
    make_server: Callable[..., Any],
    run_git: Callable[..., str],
) -> None:
    """直コミットを許可していない種類の文書を消す（異常系）。"""
    # 準備
    direct = make_direct_commit_source(files={"rules/r1.yaml": "id: r1\nname: 規約 1\n"})
    env = make_server(direct.spec)
    rule = direct.develop / "rules" / "r1.yaml"
    remote_before = run_git(direct.bare, "rev-parse", "develop").strip()
    head = run_git(direct.develop, "rev-parse", "HEAD").strip()
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(direct.local),
        source="sample",
        targets=[{"id": "r1", "expected_version": content_hash(rule.read_text(encoding="utf-8"))}],
        commit={"message": "docs: rule を消す"},
    )
    # 検証
    assert result.is_error
    assert "rule は直コミットを許可していない種類です" in result.text
    assert "index: 0" in result.text
    assert run_git(direct.bare, "rev-parse", "develop").strip() == remote_before
    assert run_git(direct.develop, "rev-parse", "HEAD").strip() == head
    assert rule.exists()


# 削除の時点の検査 `guard`。標準入力の文書が doc-1 なら常に違反を出し、doc-2 なら
# PROJECT_INDEX_DELETE_IDS に doc-1 が無いときだけ違反を出す（PROJECT_INDEX_VALIDATE_ON が delete のときだけ）
GUARD_SCRIPT = (
    "import json, os, sys\n"
    "doc_id = sys.stdin.read().splitlines()[0].removeprefix('id: ')\n"
    "ids = os.environ.get('PROJECT_INDEX_DELETE_IDS', '').split()\n"
    "on_delete = os.environ.get('PROJECT_INDEX_VALIDATE_ON') == 'delete'\n"
    "bad = on_delete and (doc_id == 'doc-1' or (doc_id == 'doc-2' and 'doc-1' not in ids))\n"
    "print(json.dumps([{'path': '$', 'rule': 'guard'}] if bad else []))\n"
)
GUARD_ROW = (
    "    validators: [guard]\n"
    "validators:\n"
    "  - id: guard\n"
    "    run: [python3, scripts/guard.py]\n"
    "    on: [delete]\n"
)
# GUARD_ROW に、書き込みの時点（`on: [write]`）だけで常に違反を出す検査 `always-bad` を加えた行
WRITE_ONLY_ROW = (
    "    validators: [guard, always-bad]\n"
    "validators:\n"
    "  - id: guard\n"
    "    run: [python3, scripts/guard.py]\n"
    "    on: [delete]\n"
    "  - id: always-bad\n"
    "    run: [python3, scripts/always_bad.py]\n"
    "    on: [write]\n"
)
ALWAYS_BAD_SCRIPT = "import json\nprint(json.dumps([{'path': '$', 'rule': 'always-bad'}]))\n"
# doc-1 だけに違反を出さない guard（2 回目の削除と、doc-1 が別の違反で failed になる確認に使う）
LENIENT_GUARD_SCRIPT = GUARD_SCRIPT.replace("doc_id == 'doc-1' or ", "")


def test_error_when_delete_validator_fails(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """on に delete を持つ validators[] が違反を返却する削除を、ファイルを削除する前に断る（異常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(WRITE_ONLY_ROW),
            "scripts/guard.py": LENIENT_GUARD_SCRIPT,
            "scripts/always_bad.py": ALWAYS_BAD_SCRIPT,
        }
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    doc_1 = worktree / "docs" / "doc-1.yaml"
    doc_2 = worktree / "docs" / "doc-2.yaml"
    only_2 = [{"id": "doc-2", "expected_version": _version(doc_2)}]
    both = [
        {"id": "doc-1", "expected_version": _version(doc_1)},
        {"id": "doc-2", "expected_version": _version(doc_2)},
    ]
    call: dict[str, Any] = {"cwd": str(source.folder), "worktree": str(worktree)}
    # 実行
    first = env.call("delete_docs", targets=only_2, **call)
    dry = env.call("delete_docs", targets=only_2, dry_run=True, **call)
    loose = env.call("delete_docs", targets=only_2, atomic=False, **call)
    files_after_first = (doc_1.is_file(), doc_2.is_file())
    second = env.call("delete_docs", targets=both, **call)
    # 検証
    assert first.is_error
    assert "ValidationFailedError" in first.text
    assert "guard" in first.text
    assert "always-bad" not in first.text
    assert dry.is_error
    assert "guard" in dry.text
    assert not loose.is_error
    assert [item["status"] for item in loose.data["results"]] == ["failed"]
    assert "guard" in json.dumps(loose.data["results"][0]["errors"], ensure_ascii=False)
    assert files_after_first == (True, True)
    assert not second.is_error
    assert [item["status"] for item in second.data["results"]] == ["deleted", "deleted"]
    assert (doc_1.is_file(), doc_2.is_file()) == (False, False)


def test_error_when_delete_validator_fails_retry(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """atomic: false で文書 1 が failed になると、文書 1 が消える前提で合格した文書 2 も削除しない（異常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(GUARD_ROW),
            "scripts/guard.py": GUARD_SCRIPT,
        }
    )
    source, env, worktree = _setup(make_source, make_server, add_worktree, files)
    doc_1 = worktree / "docs" / "doc-1.yaml"
    doc_2 = worktree / "docs" / "doc-2.yaml"
    targets = [
        {"id": "doc-1", "expected_version": _version(doc_1)},
        {"id": "doc-2", "expected_version": _version(doc_2)},
    ]
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        targets=targets,
        atomic=False,
    )
    # 検証
    assert not result.is_error
    assert [item["status"] for item in result.data["results"]] == ["failed", "failed"]
    assert (doc_1.is_file(), doc_2.is_file()) == (True, True)


def test_error_when_sqlite_kind_deleted(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
) -> None:
    """SQLite の表の行の文書を指す削除を断る（異常系）。"""
    from tests.integration.server.conftest import sqlite_files, write_notes_db

    # 準備
    source, env, worktree = _setup(make_source, make_server, add_worktree, sqlite_files())
    db = write_notes_db(source.folder)
    db_before = db.read_bytes()
    target = worktree / "docs" / "doc-1.yaml"
    # 実行
    result = env.call(
        "delete_docs",
        cwd=str(source.folder),
        worktree=str(worktree),
        targets=[
            {"id": "doc-1", "expected_version": _version(target)},
            {"id": "n1", "expected_version": "000000"},
        ],
    )
    # 検証
    assert result.is_error is True
    assert result.text.startswith("ReadOnlyKindError")
    assert "targets[1]" in result.text
    assert "notes_db" in result.text
    assert target.exists()
    assert db.read_bytes() == db_before

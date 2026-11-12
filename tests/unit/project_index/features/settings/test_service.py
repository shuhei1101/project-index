from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from project_index.features.settings.query import read_settings_file
from project_index.features.settings.service import (
    add_source,
    delete_source,
    patch_source,
    save_sources,
)
from project_index.features.settings.types import (
    SettingsVersionMismatchError,
    SourceEntry,
    SourcePatch,
    SourceRowNotFoundError,
    TerminalConfig,
    TerminalConfigInvalidError,
)
from project_index.shared.yaml_io import load_yaml

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.sources.types import SourceStatus

SETTINGS_TEXT = (
    'version: "1"\n'
    "clone: /tmp/clone\n"
    "port: 8786  # ポート\n"
    "sources:\n"
    "  - config: /tmp/a/project-index.yaml\n"
)


@pytest.fixture
def settings_path(tmp_path: Path) -> Path:
    """端末の設定のファイルを書いてパスを返す。"""
    path = tmp_path / "settings.yaml"
    path.write_text(SETTINGS_TEXT, encoding="utf-8")
    return path


@pytest.fixture
def fake_reload(
    make_status: Callable[..., SourceStatus],
) -> tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]]:
    """`serving` を 2 つ返し、呼ばれた端末の設定を記録する配信元の読み直しの偽物。"""
    calls: list[TerminalConfig] = []

    def _reload(terminal: TerminalConfig) -> list[SourceStatus]:
        calls.append(terminal)
        return [make_status("a", 0), make_status("b", 1)]

    return _reload, calls


def test_save_sources(
    settings_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """sources だけを書き換えコメントを保つ（正常系）。"""
    # 準備
    reload, calls = fake_reload
    sources = [
        make_entry("/tmp/a/project-index.yaml", source_id="a"),
        make_entry("/tmp/b/project-index.yaml", source_id="b"),
    ]
    # 実行
    result = save_sources(sources, path=settings_path, reload=reload, lock=threading.Lock())
    # 検証
    text = settings_path.read_text(encoding="utf-8")
    assert text.count("config:") == 2
    assert "port: 8786  # ポート" in text
    assert len(calls) == 1
    assert len(calls[0].sources) == 2
    assert [status.id for status in result.statuses] == ["a", "b"]


def test_save_sources_when_defaults(
    settings_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """既定値のキーを書かない（正常系）。"""
    # 準備
    reload, _ = fake_reload
    sources = [make_entry("/tmp/a/project-index.yaml", source_id="a", enabled=True)]
    # 実行
    save_sources(sources, path=settings_path, reload=reload, lock=threading.Lock())
    # 検証
    text = settings_path.read_text(encoding="utf-8")
    row = load_yaml(text)["sources"][0]
    assert "enabled" not in text
    assert "scope" not in text
    assert row["config"] == ["/tmp/a/project-index.yaml"]


def test_save_sources_when_outside_read_false(
    settings_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """既定値と違う outside_read を書く（正常系）。"""
    # 準備
    reload, _ = fake_reload
    sources = [make_entry("/tmp/a/project-index.yaml", source_id="a", outside_read=False)]
    # 実行
    save_sources(sources, path=settings_path, reload=reload, lock=threading.Lock())
    # 検証
    text = settings_path.read_text(encoding="utf-8")
    assert "outside_read: false" in text


def test_save_sources_when_unsent_keys(
    tmp_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
) -> None:
    """行に含めなかったキーをファイルの同じ配信元の行の値で埋める（正常系）。"""
    # 準備
    reload, _ = fake_reload
    path = tmp_path / "settings.yaml"
    path.write_text(
        'version: "1"\n'
        "clone: /tmp/clone\n"
        "sources:\n"
        "  - id: extra\n"
        "    config: /tmp/extra/project-index.yaml\n"
        "    enabled: false\n"
        "    outside_read: false\n"
        "    scope:\n"
        "      read: [/tmp/old/**]\n"
        "      write: [/tmp/write/**]\n",
        encoding="utf-8",
    )
    sent = SourceEntry.model_validate(
        {
            "id": "extra",
            "config": "/tmp/extra/project-index.yaml",
            "scope": {"read": ["/tmp/new/**"]},
        }
    )
    # 実行
    save_sources([sent], path=path, reload=reload, lock=threading.Lock())
    # 検証
    row = load_yaml(path.read_text(encoding="utf-8"))["sources"][0]
    assert row["enabled"] is False
    assert row["outside_read"] is False
    assert row["scope"] == {"read": ["/tmp/new/**"], "write": ["/tmp/write/**"]}


def test_save_sources_when_sent_keys_override(
    tmp_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
) -> None:
    """行に含めたキーは送った値で書く（正常系）。"""
    # 準備
    reload, _ = fake_reload
    path = tmp_path / "settings.yaml"
    path.write_text(
        'version: "1"\n'
        "clone: /tmp/clone\n"
        "sources:\n"
        "  - id: extra\n"
        "    config: /tmp/extra/project-index.yaml\n"
        "    outside_read: false\n",
        encoding="utf-8",
    )
    sent = SourceEntry.model_validate(
        {"id": "extra", "config": "/tmp/extra/project-index.yaml", "outside_read": True}
    )
    # 実行
    save_sources([sent], path=path, reload=reload, lock=threading.Lock())
    # 検証
    row = load_yaml(path.read_text(encoding="utf-8"))["sources"][0]
    assert "outside_read" not in row


def test_save_sources_when_no_same_row(
    tmp_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
) -> None:
    """ファイルに同じ配信元の行が無い行は埋めない（正常系）。"""
    # 準備
    reload, _ = fake_reload
    path = tmp_path / "settings.yaml"
    path.write_text(
        'version: "1"\n'
        "clone: /tmp/clone\n"
        "sources:\n"
        "  - id: sample\n"
        "    config: /tmp/extra/project-index.yaml\n"
        "    outside_read: false\n",
        encoding="utf-8",
    )
    sent = SourceEntry.model_validate({"id": "extra", "config": "/tmp/extra/project-index.yaml"})
    # 実行
    save_sources([sent], path=path, reload=reload, lock=threading.Lock())
    # 検証
    row = load_yaml(path.read_text(encoding="utf-8"))["sources"][0]
    assert row["id"] == "extra"
    assert "outside_read" not in row


def test_save_sources_when_current_row_invalid(
    tmp_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
) -> None:
    """ファイルに読めない行があっても送った行で保存する（正常系）。"""
    # 準備
    reload, calls = fake_reload
    path = tmp_path / "settings.yaml"
    path.write_text(
        'version: "1"\n'
        "clone: /tmp/clone\n"
        "sources:\n"
        "  - id: extra\n"
        "    config: /tmp/extra/project-index.yaml\n"
        "    outside-read: false\n",
        encoding="utf-8",
    )
    sent = SourceEntry.model_validate({"id": "extra", "config": "/tmp/extra/project-index.yaml"})
    # 実行
    save_sources([sent], path=path, reload=reload, lock=threading.Lock())
    # 検証
    row = load_yaml(path.read_text(encoding="utf-8"))["sources"][0]
    assert row == {"id": "extra", "config": ["/tmp/extra/project-index.yaml"]}
    assert len(calls) == 1


def test_save_sources_when_invalid(
    settings_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """検証に通らない（異常系）。"""
    # 準備
    reload, calls = fake_reload
    sources = [
        make_entry("/tmp/a/project-index.yaml", source_id="a"),
        make_entry("/tmp/b/project-index.yaml", source_id="a"),
    ]
    # 実行・検証
    with pytest.raises(TerminalConfigInvalidError):
        save_sources(sources, path=settings_path, reload=reload, lock=threading.Lock())
    assert settings_path.read_text(encoding="utf-8") == SETTINGS_TEXT
    assert calls == []


def test_add_source(
    settings_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """末尾に追加して読み直す（正常系）。"""
    # 準備
    reload, calls = fake_reload
    entry = make_entry("/tmp/b/project-index.yaml", source_id="b")
    # 実行
    result = add_source(entry, path=settings_path, reload=reload, lock=threading.Lock())
    # 検証
    text = settings_path.read_text(encoding="utf-8")
    data = load_yaml(text)
    assert result.result == "added"
    assert [row["config"] for row in data["sources"]] == [
        "/tmp/a/project-index.yaml",
        ["/tmp/b/project-index.yaml"],
    ]
    assert "port: 8786  # ポート" in text
    assert len(calls) == 1


def test_add_source_when_same_id(
    tmp_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """同じ id の行があれば追加しない（正常系）。"""
    # 準備
    path = tmp_path / "settings.yaml"
    path.write_text(
        'version: "1"\nclone: /tmp/clone\nsources:\n'
        "  - id: b\n    config: [/tmp/b/project-index.yaml]\n",
        encoding="utf-8",
    )
    before = path.read_text(encoding="utf-8")
    reload, calls = fake_reload
    # 実行
    same = add_source(
        make_entry("/tmp/b/project-index.yaml", source_id="b"),
        path=path,
        reload=reload,
        lock=threading.Lock(),
    )
    other = add_source(
        make_entry("/tmp/c/project-index.yaml", source_id="b"),
        path=path,
        reload=reload,
        lock=threading.Lock(),
    )
    # 検証
    assert (same.result, same.same) == ("exists", True)
    assert (other.result, other.same) == ("exists", False)
    assert path.read_text(encoding="utf-8") == before
    assert calls == []


def _unnamed_settings(tmp_path: Path) -> tuple[Path, Path]:
    """`name: sample` の配信元の設定と、それを `id` を省略して指す行を持つ端末の設定を書く。"""
    config = tmp_path / "sample" / "project-index.yaml"
    config.parent.mkdir()
    config.write_text('version: "3"\nname: sample\n', encoding="utf-8")
    path = tmp_path / "settings.yaml"
    path.write_text(
        f'version: "1"\nclone: /tmp/clone\nsources:\n  - config: [{config}]\n',
        encoding="utf-8",
    )
    return path, config


def test_add_source_when_same_name(
    tmp_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """id を省略した行どうしは設定の name で照合する（正常系）。"""
    # 準備
    path, config = _unnamed_settings(tmp_path)
    before = path.read_text(encoding="utf-8")
    reload, calls = fake_reload
    # 実行
    result = add_source(make_entry(str(config)), path=path, reload=reload, lock=threading.Lock())
    # 検証
    assert (result.result, result.same) == ("exists", True)
    assert path.read_text(encoding="utf-8") == before
    assert calls == []


def test_add_source_when_id_matches_name(
    tmp_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """id を書いた行を、id を省略した既存の行の name と照合する（正常系）。"""
    # 準備
    path, config = _unnamed_settings(tmp_path)
    before = path.read_text(encoding="utf-8")
    reload, calls = fake_reload
    # 実行
    result = add_source(
        make_entry(str(config), source_id="sample"),
        path=path,
        reload=reload,
        lock=threading.Lock(),
    )
    # 検証
    assert (result.result, result.same) == ("exists", False)
    assert path.read_text(encoding="utf-8") == before
    assert calls == []


def test_add_source_when_invalid(
    settings_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """加えた後にスキーマに通らない（異常系）。"""
    # 準備
    reload, calls = fake_reload
    before = settings_path.read_text(encoding="utf-8")
    entry = make_entry("/tmp/b/project-index.yaml", source_id="Sample Docs")
    # 実行・検証
    with pytest.raises(TerminalConfigInvalidError):
        add_source(entry, path=settings_path, reload=reload, lock=threading.Lock())
    assert settings_path.read_text(encoding="utf-8") == before
    assert calls == []


def test_save_sources_when_version_matched(
    settings_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """内容のバージョンが一致すれば保存する（正常系）。"""
    # 準備
    reload, _ = fake_reload
    _, version = read_settings_file(settings_path)
    sources = [make_entry("/tmp/b/project-index.yaml", source_id="b")]
    # 実行
    result = save_sources(
        sources,
        expected_version=version,
        path=settings_path,
        reload=reload,
        lock=threading.Lock(),
    )
    # 検証
    assert "/tmp/b/project-index.yaml" in settings_path.read_text(encoding="utf-8")
    assert result.version == read_settings_file(settings_path)[1]
    assert result.version != version


def test_save_sources_when_version_outdated(
    settings_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """内容のバージョンが古い（異常系）。"""
    # 準備
    reload, calls = fake_reload
    _, old = read_settings_file(settings_path)
    settings_path.write_text(SETTINGS_TEXT + "# memo\n", encoding="utf-8")
    sources = [make_entry("/tmp/b/project-index.yaml", source_id="b")]
    # 実行・検証
    with pytest.raises(SettingsVersionMismatchError) as caught:
        save_sources(
            sources, expected_version=old, path=settings_path, reload=reload, lock=threading.Lock()
        )
    assert caught.value.current == read_settings_file(settings_path)[1]
    assert settings_path.read_text(encoding="utf-8") == SETTINGS_TEXT + "# memo\n"
    assert calls == []


def test_add_source_when_version_outdated(
    settings_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """内容のバージョンが古い（異常系）。"""
    # 準備
    reload, calls = fake_reload
    _, old = read_settings_file(settings_path)
    settings_path.write_text(SETTINGS_TEXT + "# memo\n", encoding="utf-8")
    entry = make_entry("/tmp/b/project-index.yaml", source_id="b")
    # 実行・検証
    with pytest.raises(SettingsVersionMismatchError):
        add_source(
            entry, expected_version=old, path=settings_path, reload=reload, lock=threading.Lock()
        )
    assert settings_path.read_text(encoding="utf-8") == SETTINGS_TEXT + "# memo\n"
    assert calls == []


TWO_ROWS_TEXT = (
    'version: "1"\n'
    "clone: /tmp/clone\n"
    "port: 8786  # ポート\n"
    "sources:\n"
    "  - id: sample\n"
    "    config: [/tmp/sample/project-index.yaml]\n"
    "  - id: extra\n"
    "    config: [/tmp/extra/project-index.yaml]\n"
    "    scope:\n"
    "      read: [/tmp/extra/**]\n"
    "      write: [/tmp/write/**]\n"
)


@pytest.fixture
def two_rows_path(tmp_path: Path) -> Path:
    """sample と extra の 2 行を持つ端末の設定を書いてパスを返す。"""
    path = tmp_path / "settings.yaml"
    path.write_text(TWO_ROWS_TEXT, encoding="utf-8")
    return path


def test_patch_source(
    two_rows_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
) -> None:
    """送ったキーだけを重ねる（正常系）。"""
    # 準備
    reload, calls = fake_reload
    _, version = read_settings_file(two_rows_path)
    patch = SourcePatch.model_validate({"outside_read": False})
    # 実行
    result = patch_source(
        "extra",
        patch,
        expected_version=version,
        path=two_rows_path,
        reload=reload,
        lock=threading.Lock(),
    )
    # 検証
    text = two_rows_path.read_text(encoding="utf-8")
    rows = load_yaml(text)["sources"]
    assert rows[0] == {"id": "sample", "config": ["/tmp/sample/project-index.yaml"]}
    assert rows[1]["outside_read"] is False
    assert rows[1]["scope"] == {"read": ["/tmp/extra/**"], "write": ["/tmp/write/**"]}
    assert "port: 8786  # ポート" in text
    assert len(calls) == 1
    assert result.version == read_settings_file(two_rows_path)[1]


def test_patch_source_when_scope_write_null(
    two_rows_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
) -> None:
    """scope.write に null を送ると既定に戻す（正常系）。"""
    # 準備
    reload, _ = fake_reload
    _, version = read_settings_file(two_rows_path)
    patch = SourcePatch.model_validate({"scope": {"write": None}})
    # 実行
    patch_source(
        "extra",
        patch,
        expected_version=version,
        path=two_rows_path,
        reload=reload,
        lock=threading.Lock(),
    )
    # 検証
    row = load_yaml(two_rows_path.read_text(encoding="utf-8"))["sources"][1]
    assert row["scope"] == {"read": ["/tmp/extra/**"]}


def _named_settings(tmp_path: Path) -> tuple[Path, Path]:
    """`name: notes` と `name: memo` の配信元の設定と、notes を `id` を省いて指す行を持つ端末の設定を書く。"""
    for name in ("notes", "memo"):
        config = tmp_path / name / "project-index.yaml"
        config.parent.mkdir()
        config.write_text(f'version: "3"\nname: {name}\n', encoding="utf-8")
    path = tmp_path / "settings.yaml"
    path.write_text(
        f'version: "1"\nclone: /tmp/clone\nsources:\n  - config: [{tmp_path / "notes" / "project-index.yaml"}]\n',
        encoding="utf-8",
    )
    return path, tmp_path / "memo" / "project-index.yaml"


def test_patch_source_when_row_without_id(
    tmp_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
) -> None:
    """id を省いた行を設定の name で指す（正常系）。"""
    # 準備
    reload, _ = fake_reload
    path, _ = _named_settings(tmp_path)
    _, version = read_settings_file(path)
    patch = SourcePatch.model_validate({"enabled": False})
    # 実行
    patch_source(
        "notes", patch, expected_version=version, path=path, reload=reload, lock=threading.Lock()
    )
    # 検証
    row = load_yaml(path.read_text(encoding="utf-8"))["sources"][0]
    assert row["enabled"] is False
    assert "id" not in row


def test_patch_source_when_version_outdated(
    two_rows_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
) -> None:
    """内容のバージョンが古い（異常系）。"""
    # 準備
    reload, calls = fake_reload
    _, old = read_settings_file(two_rows_path)
    two_rows_path.write_text(TWO_ROWS_TEXT + "# memo\n", encoding="utf-8")
    patch = SourcePatch.model_validate({"outside_read": False})
    # 実行・検証
    with pytest.raises(SettingsVersionMismatchError):
        patch_source(
            "extra",
            patch,
            expected_version=old,
            path=two_rows_path,
            reload=reload,
            lock=threading.Lock(),
        )
    assert two_rows_path.read_text(encoding="utf-8") == TWO_ROWS_TEXT + "# memo\n"
    assert calls == []


def test_patch_source_when_not_found(
    settings_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
) -> None:
    """指した行が無い（異常系）。"""
    # 準備
    reload, calls = fake_reload
    _, version = read_settings_file(settings_path)
    patch = SourcePatch.model_validate({"enabled": False})
    # 実行・検証
    with pytest.raises(SourceRowNotFoundError) as caught:
        patch_source(
            "extra",
            patch,
            expected_version=version,
            path=settings_path,
            reload=reload,
            lock=threading.Lock(),
        )
    assert caught.value.source_id == "extra"
    assert settings_path.read_text(encoding="utf-8") == SETTINGS_TEXT
    assert calls == []


def test_patch_source_when_id_changes(
    tmp_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
) -> None:
    """id を省いた行の配信元の ID が変わる（異常系）。"""
    # 準備
    reload, calls = fake_reload
    path, memo = _named_settings(tmp_path)
    before, version = read_settings_file(path)
    patch = SourcePatch.model_validate({"config": str(memo)})
    # 実行・検証
    with pytest.raises(TerminalConfigInvalidError) as caught:
        patch_source(
            "notes",
            patch,
            expected_version=version,
            path=path,
            reload=reload,
            lock=threading.Lock(),
        )
    assert [violation.path for violation in caught.value.violations] == ["source.config"]
    assert path.read_text(encoding="utf-8") == before
    assert calls == []


def test_patch_source_when_invalid(
    two_rows_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
) -> None:
    """重ねた後にスキーマに通らない（異常系）。"""
    # 準備
    reload, calls = fake_reload
    _, version = read_settings_file(two_rows_path)
    patch = SourcePatch.model_validate({"scope": {"read": [""]}})
    # 実行・検証
    with pytest.raises(TerminalConfigInvalidError):
        patch_source(
            "extra",
            patch,
            expected_version=version,
            path=two_rows_path,
            reload=reload,
            lock=threading.Lock(),
        )
    assert two_rows_path.read_text(encoding="utf-8") == TWO_ROWS_TEXT
    assert calls == []


def test_delete_source(
    two_rows_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
) -> None:
    """指した行だけを削除する（正常系）。"""
    # 準備
    reload, calls = fake_reload
    _, version = read_settings_file(two_rows_path)
    # 実行
    result = delete_source(
        "extra",
        expected_version=version,
        path=two_rows_path,
        reload=reload,
        lock=threading.Lock(),
    )
    # 検証
    text = two_rows_path.read_text(encoding="utf-8")
    assert load_yaml(text)["sources"] == [
        {"id": "sample", "config": ["/tmp/sample/project-index.yaml"]}
    ]
    assert "port: 8786  # ポート" in text
    assert len(calls) == 1
    assert [entry.id for entry in calls[0].sources] == ["sample"]
    assert result.version == read_settings_file(two_rows_path)[1]


def test_delete_source_when_version_outdated(
    two_rows_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
) -> None:
    """内容のバージョンが古い（異常系）。"""
    # 準備
    reload, calls = fake_reload
    _, old = read_settings_file(two_rows_path)
    two_rows_path.write_text(TWO_ROWS_TEXT + "# memo\n", encoding="utf-8")
    # 実行・検証
    with pytest.raises(SettingsVersionMismatchError):
        delete_source(
            "extra", expected_version=old, path=two_rows_path, reload=reload, lock=threading.Lock()
        )
    assert two_rows_path.read_text(encoding="utf-8") == TWO_ROWS_TEXT + "# memo\n"
    assert calls == []


def test_delete_source_when_not_found(
    settings_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
) -> None:
    """指した行が無い（異常系）。"""
    # 準備
    reload, calls = fake_reload
    _, version = read_settings_file(settings_path)
    # 実行・検証
    with pytest.raises(SourceRowNotFoundError):
        delete_source(
            "extra",
            expected_version=version,
            path=settings_path,
            reload=reload,
            lock=threading.Lock(),
        )
    assert settings_path.read_text(encoding="utf-8") == SETTINGS_TEXT
    assert calls == []

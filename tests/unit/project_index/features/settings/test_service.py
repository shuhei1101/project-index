from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from project_index.features.settings.service import add_source, save_sources
from project_index.features.settings.types import (
    SourceEntry,
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
    assert [status.id for status in result] == ["a", "b"]


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


UNKNOWN_KEY_TEXT = (
    'version: "1"\n'
    "clone: /tmp/clone\n"
    "# MindStella の設定\n"
    "mindstella:\n"
    "  threads: 3  # 同時に動かす数\n"
    "sources:\n"
    "  - config: /tmp/a/project-index.yaml\n"
)


def test_save_sources_when_unknown_top_level_key(
    tmp_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """最上位の知らないキーを残して保存する（正常系）。"""
    # 準備
    path = tmp_path / "settings.yaml"
    path.write_text(UNKNOWN_KEY_TEXT, encoding="utf-8")
    reload, _ = fake_reload
    sources = [make_entry("/tmp/a/project-index.yaml", source_id="sample")]
    # 実行
    save_sources(sources, path=path, reload=reload, lock=threading.Lock())
    # 検証
    text = path.read_text(encoding="utf-8")
    assert "# MindStella の設定\nmindstella:\n  threads: 3  # 同時に動かす数\n" in text


def test_add_source_when_unknown_top_level_key(
    tmp_path: Path,
    fake_reload: tuple[Callable[[TerminalConfig], list[SourceStatus]], list[TerminalConfig]],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """最上位の知らないキーを残して 1 行を追加する（正常系）。"""
    # 準備
    path = tmp_path / "settings.yaml"
    path.write_text(UNKNOWN_KEY_TEXT, encoding="utf-8")
    reload, _ = fake_reload
    entry = make_entry("/tmp/b/project-index.yaml", source_id="extra")
    # 実行
    result = add_source(entry, path=path, reload=reload, lock=threading.Lock())
    # 検証
    text = path.read_text(encoding="utf-8")
    assert result.result == "added"
    assert "# MindStella の設定\nmindstella:\n  threads: 3  # 同時に動かす数\n" in text

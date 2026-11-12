from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


def test_normal(make_source: Callable[..., Any], make_server: Callable[..., Any]) -> None:
    """端末の設定に追加した配信元の配信を始める（正常系）。"""
    # 準備
    sample = make_source("sample")
    notes = make_source("notes", git=False)
    env = make_server(sample)
    env.rewrite_settings(sample, notes)
    # 実行
    result = env.call_admin("reload", format="json")
    # 検証
    found = env.call(
        "search_docs", cwd=str(notes.folder), source="notes", view="ids", format="json"
    )
    described = env.call("describe", cwd=str(sample.folder))
    assert result.data["added"] == ["notes"]
    assert "removed" not in result.data
    assert "not_served" not in result.data
    assert {item["id"] for item in found.data["items"]} == {"doc-1", "doc-2"}
    assert not described.is_error


def test_normal_when_source_becomes_invalid(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """配信元の設定を壊して読み直すと、その配信元を外して返す（正常系）。"""
    # 準備
    sample = make_source("sample", sample_file_set(), git=False)
    env = make_server(sample)
    (sample.folder / "project-index.yaml").write_text(
        "name: sample\ndocuments:\n  - id: sample\n    schema: schemas/sample.schema.yaml\n",
        encoding="utf-8",
    )
    # 実行
    result = env.call_admin("reload", format="json")
    # 検証
    searched = env.call("search_docs", cwd=str(sample.folder), source="sample")
    not_served = result.data["not_served"]
    assert [item["id"] for item in not_served] == ["sample"]
    assert any("documents[0].paths" in error for error in not_served[0]["errors"])
    assert searched.is_error
    assert searched.text.startswith("SourceNotServedError")


def test_error_when_terminal_config_invalid(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """端末の設定がスキーマに違反すると、配信元の一覧を変えずに断る（異常系）。"""
    # 準備
    sample = make_source("sample")
    env = make_server(sample)
    env.settings_path.write_text(
        env.settings_path.read_text(encoding="utf-8").replace("    config:", "    configs:"),
        encoding="utf-8",
    )
    # 実行
    result = env.call_admin("reload")
    # 検証
    searched = env.call("search_docs", cwd=str(sample.folder), source="sample", view="ids")
    assert result.is_error
    assert "sources[0].config" in result.text
    assert not searched.is_error

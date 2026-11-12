from __future__ import annotations

from typing import TYPE_CHECKING, Any

from project_index.shared.yaml_io import load_yaml

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

NAV_CONFIG = (
    "# 配信元の設定\n"
    "name: sample\n"
    "description: サンプルの配信元\n"
    "default_ref: develop\n"
    "documents:\n"
    "  - id: sample\n"
    "    paths: [docs/*.yaml]\n"
    "    schema: schemas/sample.schema.yaml\n"
    "nav:\n"
    "  tabs:\n"
    "    - title: すべて\n"
    "      items:\n"
    "        - auto: {document: sample}\n"
)
# auto の項目 1 つだけを持つタブ mcp
AUTO_ONLY_NAV = (
    "    - title: mcp\n"
    "      items:\n"
    "        - auto: {filter: {field: tags, op: eq, values: [mcp]}}\n"
)
LOCAL_NAV = (
    "name: layered\n"
    "nav:\n"
    "  tabs:\n"
    "    - title: ローカル\n"
    "      items:\n"
    "        - auto: {document: sample}\n"
)
BROKEN_CONFIG = "name: sample\ndocuments:\n  - id: sample\n    paths: [docs/*.yaml\n"
MCP_TAB = {
    "title": "mcp",
    "items": [{"auto": {"filter": {"field": "tags", "op": "eq", "values": ["mcp"]}}}],
}
DESIGN_ITEMS = {
    "items": [{"auto": {"filter": {"field": "tags", "op": "eq", "values": ["設計"]}}}],
}
NONE_TAB = {
    "title": "none",
    "items": [{"auto": {"filter": {"field": "tags", "op": "eq", "values": ["none"]}}}],
}
FOLDERS_TAB = {
    "title": "folders",
    "items": [{"auto": {"document": "sample", "group_by": "@folder"}}],
}
BAD_TAB = {
    "title": "bad",
    "items": [{"auto": {"filter": {"field": "tags", "op": "like", "values": ["mcp"]}}}],
}
NEW_TAB_PATH = "nav.tabs[1].items[0].auto"


def _tagged_files(
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
    nav_extra: str = "",
) -> dict[str, str]:
    """文書 1〜3 にタグを付け、nav と description・コメントを持つ配信元のファイル一式を返す。"""
    return sample_file_set(
        **{
            "project-index.yaml": NAV_CONFIG + nav_extra,
            "docs/doc-1.yaml": sample_doc_text("doc-1", "文書 1", tags=["mcp"]),
            "docs/doc-2.yaml": sample_doc_text("doc-2", "文書 2", tags=["設計"]),
            "docs/doc-3.yaml": sample_doc_text("doc-3", "文書 3", tags=["mcp", "設計"]),
        }
    )


def _setup(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    files: dict[str, str],
) -> tuple[Any, Path]:
    """ワークツリー x を持つ sample を起動し、環境とワークツリーの project-index.yaml を返す。"""
    source = make_source("sample", files)
    worktree = add_worktree(source.folder, "x")
    return make_server(source), worktree / "project-index.yaml"


def _counts(result: Any) -> dict[str, int]:
    """`counts` を auto のキーのパスと文書の数の対応にする。"""
    return {item["path"]: item["count"] for item in result.data["counts"]}


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """タブを追加し、書いた後の nav と条件に当たる文書の数を返す（正常系）。"""
    # 準備
    files = _tagged_files(sample_file_set, sample_doc_text)
    env, config = _setup(make_source, make_server, add_worktree, files)
    # 実行
    added = env.call_admin(
        "write_nav",
        path=str(config.parent),
        operations=[{"op": "add", "tab": "mcp", "value": MCP_TAB}],
        format="json",
    )
    after_add = load_yaml(config.read_text(encoding="utf-8"))
    updated = env.call_admin(
        "write_nav",
        path=str(config.parent),
        operations=[{"op": "update", "tab": "mcp", "value": DESIGN_ITEMS}],
        format="json",
    )
    text = config.read_text(encoding="utf-8")
    after_update = load_yaml(text)
    # 検証
    assert not added.is_error
    assert [tab["title"] for tab in after_add["nav"]["tabs"]] == ["すべて", "mcp"]
    assert _counts(added)[NEW_TAB_PATH] == 2
    assert not updated.is_error
    assert after_update["nav"]["tabs"][1]["items"][0]["auto"]["filter"]["values"] == ["設計"]
    assert _counts(updated)[NEW_TAB_PATH] == 2
    assert text.startswith("# 配信元の設定\n")
    assert after_update["description"] == "サンプルの配信元"
    assert not added.data.get("warnings")
    assert not updated.data.get("warnings")


def test_normal_when_filter_matches_nothing(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """どの文書にも当たらない条件も書いたうえで警告を返す（正常系）。"""
    # 準備
    files = _tagged_files(sample_file_set, sample_doc_text)
    env, config = _setup(make_source, make_server, add_worktree, files)
    # 実行
    result = env.call_admin(
        "write_nav",
        path=str(config.parent),
        operations=[{"op": "add", "tab": "none", "value": NONE_TAB}],
        format="json",
    )
    # 検証
    written = load_yaml(config.read_text(encoding="utf-8"))
    assert not result.is_error
    assert [tab["title"] for tab in written["nav"]["tabs"]] == ["すべて", "none"]
    assert _counts(result)[NEW_TAB_PATH] == 0
    assert len(result.data["warnings"]) == 1
    assert "none" in result.data["warnings"][0]["rule"]


def test_error_when_nav_invalid(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """check_filter に通らない条件を書かない（異常系）。"""
    # 準備
    files = _tagged_files(sample_file_set, sample_doc_text)
    env, config = _setup(make_source, make_server, add_worktree, files)
    before = config.read_text(encoding="utf-8")
    # 実行
    result = env.call_admin(
        "write_nav",
        path=str(config.parent),
        operations=[{"op": "add", "tab": "bad", "value": BAD_TAB}],
    )
    # 検証
    assert result.is_error
    assert "NavInvalidError" in result.text
    assert "op" in result.text
    assert "like" in result.text
    assert config.read_text(encoding="utf-8") == before


def test_error_when_tab_missing(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """無いタブの修正を断る（異常系）。"""
    # 準備
    files = _tagged_files(sample_file_set, sample_doc_text)
    env, config = _setup(make_source, make_server, add_worktree, files)
    before = config.read_text(encoding="utf-8")
    # 実行
    result = env.call_admin(
        "write_nav",
        path=str(config.parent),
        operations=[{"op": "update", "tab": "missing", "value": DESIGN_ITEMS}],
    )
    # 検証
    assert result.is_error
    assert "InvalidArgumentError" in result.text
    assert "すべて" in result.text
    assert config.read_text(encoding="utf-8") == before


def test_error_when_config_missing(tmp_path: Path, make_server: Callable[..., Any]) -> None:
    """project-index.yaml が無いフォルダを断る（異常系）。"""
    # 準備
    env = make_server()
    folder = tmp_path / "empty"
    folder.mkdir()
    # 実行
    result = env.call_admin(
        "write_nav",
        path=str(folder),
        operations=[{"op": "add", "tab": "mcp", "value": MCP_TAB}],
    )
    # 検証
    assert result.is_error
    assert "ConfigNotFoundError" in result.text
    assert "project-index.yaml" in result.text


def test_error_when_config_unparsable(
    tmp_path: Path,
    make_server: Callable[..., Any],
    write_files: Callable[[Path, dict[str, str]], None],
) -> None:
    """読めない project-index.yaml を断る（異常系）。"""
    # 準備
    env = make_server()
    folder = tmp_path / "broken"
    write_files(folder, {"project-index.yaml": BROKEN_CONFIG})
    # 実行
    result = env.call_admin(
        "write_nav",
        path=str(folder),
        operations=[{"op": "add", "tab": "mcp", "value": MCP_TAB}],
    )
    # 検証
    assert result.is_error
    assert "ConfigParseError" in result.text
    assert ":4:" in result.text
    assert (folder / "project-index.yaml").read_text(encoding="utf-8") == BROKEN_CONFIG


def test_error_when_item_not_group(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
    sample_config_text: Callable[..., str],
) -> None:
    """名前を持たない項目を指す操作と、後に重ねた設定が nav を持つ配信元への書き込みを断る（異常系）。"""
    # 準備
    sample = make_source("sample", _tagged_files(sample_file_set, sample_doc_text, AUTO_ONLY_NAV))
    worktree = add_worktree(sample.folder, "x")
    layered_files = sample_file_set(
        **{
            "base/project-index.yaml": sample_config_text(name="layered"),
            "local/project-index.yaml": LOCAL_NAV,
        }
    )
    layered = make_source(
        "layered",
        layered_files,
        git=False,
        config_names=("base/project-index.yaml", "local/project-index.yaml"),
    )
    env = make_server(sample, layered)
    config = worktree / "project-index.yaml"
    base = layered.folder / "base" / "project-index.yaml"
    local = layered.folder / "local" / "project-index.yaml"
    before = (config.read_text(encoding="utf-8"), base.read_text(encoding="utf-8"))
    # 実行
    auto_item = env.call_admin(
        "write_nav",
        path=str(worktree),
        operations=[{"op": "update", "tab": "mcp", "item": "auto", "value": DESIGN_ITEMS}],
    )
    overridden = env.call_admin(
        "write_nav",
        path=str(base),
        operations=[{"op": "add", "tab": "x", "value": {"title": "x", "items": []}}],
    )
    # 検証
    assert auto_item.is_error
    assert "InvalidArgumentError" in auto_item.text
    assert overridden.is_error
    assert "InvalidArgumentError" in overridden.text
    assert str(local) in overridden.text
    assert (config.read_text(encoding="utf-8"), base.read_text(encoding="utf-8")) == before


def test_normal_when_group_by_folder(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    add_worktree: Callable[..., Path],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """group_by: '@folder' の auto を検証に通して書き、文書の数を返す（正常系）。"""
    # 準備
    files = _tagged_files(sample_file_set, sample_doc_text)
    env, config = _setup(make_source, make_server, add_worktree, files)
    # 実行
    result = env.call_admin(
        "write_nav",
        path=str(config.parent),
        operations=[{"op": "add", "tab": "folders", "value": FOLDERS_TAB}],
        format="json",
    )
    written = load_yaml(config.read_text(encoding="utf-8"))
    # 検証
    assert not result.is_error
    assert [tab["title"] for tab in written["nav"]["tabs"]] == ["すべて", "folders"]
    assert written["nav"]["tabs"][1]["items"][0]["auto"]["group_by"] == "@folder"
    assert _counts(result)[NEW_TAB_PATH] == 3
    assert not result.data.get("warnings")

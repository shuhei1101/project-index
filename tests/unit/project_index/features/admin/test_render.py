from __future__ import annotations

import dataclasses

from project_index.features.admin.render import (
    _source_row,
    render_check,
    render_reload,
    render_status,
)
from project_index.features.admin.types import (
    CheckProjectResult,
    CheckSync,
    NotServedItem,
    ReloadResult,
    ServerStatus,
    SourceState,
    SyncCounts,
    SyncItem,
    TerminalState,
)
from project_index.shared.errors import Violation


def _serving(source_id: str, sync: tuple[int, int, int] = (0, 0, 0)) -> SourceState:
    """設定のバージョンが同じ配信中の配信元の状態を作る。"""
    return SourceState(
        id=source_id,
        status="serving",
        errors=[],
        config_version="1",
        version_state="current",
        sync=SyncCounts(
            missing_refs=sync[0],
            unindexed_files=sync[1],
            missing_body_files=sync[2],
            unresolved_related=0,
        ),
    )


def _not_served(source_id: str, errors: list[str]) -> SourceState:
    """検証で外した配信元の状態を作る。"""
    return SourceState(
        id=source_id,
        status="not_served",
        errors=errors,
        config_version=None,
        version_state=None,
        sync=None,
    )


def test_render_status() -> None:
    """配信元の表を組み立てる（正常系）。"""
    # 準備
    status = ServerStatus(
        address="http://127.0.0.1:8786/",
        version="0.2.0",
        pid=4242,
        terminal=TerminalState(
            file="/home/u/.config/project-index/settings.yaml", version_state="current"
        ),
        sources=[
            _serving("sample"),
            _not_served("broken", ["documents[0].paths: 必須のキーが無い"]),
        ],
    )
    # 実行
    result = render_status(status)
    # 検証
    assert result.splitlines() == [
        "http://127.0.0.1:8786/ project-index 0.2.0（pid 4242）",
        "端末の設定: /home/u/.config/project-index/settings.yaml（current）",
        "| source | 状態 | 設定のバージョン | 索引の同期 |",
        "| --- | --- | --- | --- |",
        "| sample | serving | 1（current） | 0 |",
        "| broken | not_served（documents[0].paths: 必須のキーが無い） | - | - |",
    ]


def test_render_status_when_no_sources() -> None:
    """配信元が無い（正常系）。"""
    # 準備
    status = ServerStatus(
        address="http://127.0.0.1:8786/",
        version="0.2.0",
        pid=4242,
        terminal=TerminalState(
            file="/home/u/.config/project-index/settings.yaml", version_state="current"
        ),
        sources=[],
    )
    # 実行
    result = render_status(status)
    # 検証
    assert result.splitlines()[2] == "配信元: なし"


def test_render_status_when_loading() -> None:
    """読み込み中（正常系）。"""
    # 準備
    status = ServerStatus(
        address="http://127.0.0.1:8786/",
        version="0.2.0",
        pid=4242,
        terminal=TerminalState(
            file="/home/u/.config/project-index/settings.yaml", version_state="current"
        ),
        sources=[],
        loading=True,
    )
    # 実行
    result = render_status(status)
    # 検証
    assert (
        result.splitlines()[2]
        == "配信元: 読み込み中（読み込みが終わっていない配信元を指す文書の MCP の呼び出しは待たされます）"
    )


def test_render_reload() -> None:
    """差と配信元の表を組み立てる（正常系）。"""
    # 準備
    reload_result = ReloadResult(
        added=["c"],
        removed=["a"],
        not_served=[NotServedItem(id="d", errors=["name: 必須のキーが無い"])],
        sources=[_serving("b")],
    )
    # 実行
    result = render_reload(reload_result)
    # 検証
    assert result.splitlines() == [
        "追加: c",
        "削除: a",
        "配信していない: d（name: 必須のキーが無い）",
        "| source | 状態 | 設定のバージョン | 索引の同期 |",
        "| --- | --- | --- | --- |",
        "| b | serving | 1（current） | 0 |",
    ]


def test_render_reload_when_no_change() -> None:
    """差が無い（正常系）。"""
    # 準備
    reload_result = ReloadResult(added=[], removed=[], not_served=[], sources=[])
    # 実行
    result = render_reload(reload_result)
    # 検証
    assert result.splitlines()[:3] == ["追加: なし", "削除: なし", "配信していない: なし"]


def test_render_check() -> None:
    """同期のずれを内訳つきで並べる（正常系）。"""
    # 準備
    check = CheckProjectResult(
        path="/home/u/repo/sample",
        registered_id="sample",
        config_version="1",
        version_state="current",
        violations=[],
        missing_paths=[],
        script_errors=[],
        sync=CheckSync(
            missing_refs=0,
            unindexed_files=1,
            missing_body_files=0,
            unresolved_related=0,
            items=[SyncItem(kind="unindexed_files", path="docs/memo.md")],
        ),
    )
    # 実行
    result = render_check(check)
    # 検証
    assert result.splitlines() == [
        "/home/u/repo/sample（登録済み: sample）",
        "設定のバージョン: 1（current）",
        "違反: なし",
        "索引の同期: 管理用の YAML に無いファイル 1 件",
        "- unindexed_files: docs/memo.md",
    ]


def test_render_check_when_violations() -> None:
    """違反を並べ、同期の行を置かない（正常系）。"""
    # 準備
    check = CheckProjectResult(
        path="/home/u/repo/sample",
        registered_id=None,
        config_version="1",
        version_state="current",
        violations=[
            Violation(path="documents[0].paths", rule="必須のキーが無い"),
            Violation(path="name", rule="必須のキーが無い"),
        ],
        missing_paths=[],
        script_errors=[],
        sync=None,
    )
    # 実行
    result = render_check(check)
    # 検証
    lines = result.splitlines()
    index = lines.index("違反: 2 件")
    assert lines[0] == "/home/u/repo/sample（未登録）"
    assert lines[index + 1 : index + 3] == [
        "- documents[0].paths: 必須のキーが無い",
        "- name: 必須のキーが無い",
    ]
    assert [line for line in lines if line.startswith("索引の同期")] == []


def test_render_check_when_items_truncated() -> None:
    """内訳を切ったことを示す（正常系）。"""
    # 準備
    check = CheckProjectResult(
        path="/home/u/repo/sample",
        registered_id="sample",
        config_version="1",
        version_state="current",
        violations=[],
        missing_paths=[],
        script_errors=[],
        sync=CheckSync(
            missing_refs=0,
            unindexed_files=51,
            missing_body_files=0,
            unresolved_related=0,
            items=[SyncItem(kind="unindexed_files", path=f"src/u{n}.py") for n in range(50)],
        ),
    )
    # 実行
    result = render_check(check)
    # 検証
    assert "（先頭 50 件）" in result


def test_source_row() -> None:
    """配信中の行に合計を書く（正常系）。"""
    # 準備
    state = _serving("sample", sync=(1, 2, 0))
    # 実行
    result = _source_row(state)
    # 検証
    assert result == "| sample | serving | 1（current） | 3 |"


def test_source_row_when_not_served() -> None:
    """配信しない理由を添える（正常系）。"""
    # 準備
    state = _not_served(
        "broken", ["name: 必須のキーが無い", "documents[0].paths: 必須のキーが無い"]
    )
    # 実行
    result = _source_row(state)
    # 検証
    assert result == (
        "| broken | not_served（name: 必須のキーが無い、documents[0].paths: 必須のキーが無い）"
        " | - | - |"
    )


def test_source_row_when_checking() -> None:
    """検査が済んでいない配信中の行（正常系）。"""
    # 準備
    state = dataclasses.replace(_serving("sample"), sync=None)
    # 実行
    result = _source_row(state)
    # 検証
    assert result == "| sample | serving | 1（current） | 検査中 |"


def test_render_write_nav() -> None:
    """数と警告を並べ、書いた nav を続ける（正常系）。"""
    from project_index.features.admin.render import render_write_nav
    from project_index.features.admin.types import WriteNavResult
    from project_index.features.read.types import NavAutoCount

    # 準備
    none_filter = {"field": "tags", "op": "eq", "values": ["none"]}
    nav = "tabs:\n  - title: mcp\n  - title: none\n"
    write_result = WriteNavResult(
        path="/home/u/repo/sample/project-index.yaml",
        nav=nav,
        counts=[
            NavAutoCount(
                path="nav.tabs[0].items[0].auto",
                tab="mcp",
                filter={"field": "tags", "op": "eq", "values": ["mcp"]},
                count=2,
            ),
            NavAutoCount(path="nav.tabs[1].items[0].auto", tab="none", filter=none_filter, count=0),
        ],
        warnings=[
            Violation(
                path="nav.tabs[1].items[0].auto.filter",
                rule="none: 条件 {} に該当する文書がありません",
            )
        ],
    )
    # 実行
    result = render_write_nav(write_result)
    # 検証
    lines = result.splitlines()
    assert lines[0] == "/home/u/repo/sample/project-index.yaml の nav を書き込みました"
    header = lines.index("| 条件 | タブ | 文書の数 |")
    assert len([line for line in lines[header + 2 :] if line.startswith("|")]) == 2
    assert lines[header + 2].endswith("| mcp | 2 |")
    assert lines[header + 3].endswith("| none | 0 |")
    warning = lines.index("警告: 1 件")
    assert lines[warning + 1] == (
        "- nav.tabs[1].items[0].auto.filter: none: 条件 {} に該当する文書がありません"
    )
    assert result.rstrip().endswith(f"```yaml\n{nav}```")

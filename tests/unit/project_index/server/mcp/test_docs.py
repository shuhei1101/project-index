from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
import threading
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from mcp.types import CallToolResult, TextContent

from project_index.features.search.types import SearchRequest, SearchResult
from project_index.features.sources.registry import SourceRegistry
from project_index.features.write.types import WriteRequest, WriteResult
from project_index.integrations.git import GitError
from project_index.main import build_handlers
from project_index.server.mcp import docs as docs_module
from project_index.server.mcp.docs import (
    INSTRUCTIONS_MAX_CHARS,
    TOOL_RESPONSE_LIMIT_SEC,
    DocsMCPServer,
    build_docs_mcp,
)
from project_index.server.mcp.result import DOCS_INSTRUCTIONS_PROMPT_ID, tool_prompt_id
from project_index.shared.errors import UnknownKindError, WorktreeLoadingError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    import pytest

    from project_index.features.access.types import Target
    from project_index.features.settings.types import SourceEntry, TerminalConfig
    from project_index.features.sources.types import ServedSource
    from project_index.shared.deadline import CallLimits

TOOL_NAMES = {
    "search_docs",
    "write_docs",
    "delete_docs",
    "describe",
    "list_changes",
    "trace_related",
    "list_match_words",
}


def test_build_docs_mcp(make_mcp_handlers: Callable[..., Any]) -> None:
    """ツールと注釈（正常系）。"""
    # 準備
    mcp = build_docs_mcp(make_mcp_handlers())
    # 実行
    tools = asyncio.run(mcp.list_tools())
    # 検証
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == TOOL_NAMES
    assert by_name["delete_docs"].annotations is not None
    assert by_name["delete_docs"].annotations.destructive_hint is True
    assert by_name["search_docs"].annotations is not None
    assert by_name["search_docs"].annotations.read_only_hint is True
    assert by_name["list_match_words"].annotations is not None
    assert by_name["list_match_words"].annotations.read_only_hint is True


def test_build_docs_mcp_when_instructions(
    make_mcp_handlers: Callable[..., Any], bundled_prompts: Any
) -> None:
    """instructions をプロンプトの YAML から描画する（正常系）。"""
    from mcp import Client

    # 準備
    mcp = build_docs_mcp(make_mcp_handlers())

    async def _initialize() -> str | None:
        async with Client(mcp, mode="legacy") as client:
            return client.instructions

    # 実行
    result = asyncio.run(_initialize())
    # 検証
    assert result is not None
    assert result == bundled_prompts.render(
        DOCS_INSTRUCTIONS_PROMPT_ID, {"sources": [], "omitted": 0}
    )
    assert "grep" in result
    assert "action:" in result
    assert "topic:" in result
    assert "tool:" in result


def test_build_docs_mcp_when_call(
    make_mcp_handlers: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """サービスへの受け渡し（正常系）。"""
    # 準備
    received: list[SearchRequest] = []

    def fake_search_docs(request: SearchRequest, **kwargs: Any) -> SearchResult:
        received.append(request)
        return SearchResult(total_count=0, returned=0, view="summary")

    monkeypatch.setattr(docs_module, "search_docs", fake_search_docs)
    mcp = build_docs_mcp(make_mcp_handlers())
    # 実行
    result = asyncio.run(mcp.call_tool("search_docs", {"source": "sample", "format": "json"}))
    # 検証
    assert isinstance(result, CallToolResult)
    assert received[0].source == "sample"
    assert result.is_error is False
    assert result.structured_content is not None


def test_build_docs_mcp_when_foreground(
    make_mcp_handlers: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """サービスの処理の間だけ要求の応答中になる（正常系）。"""
    # 準備
    handlers = make_mcp_handlers()
    seen: list[bool] = []

    def fake_search_docs(request: SearchRequest, **kwargs: Any) -> SearchResult:
        seen.append(handlers.gate.active)
        return SearchResult(total_count=0, returned=0, view="summary")

    monkeypatch.setattr(docs_module, "search_docs", fake_search_docs)
    mcp = build_docs_mcp(handlers)
    # 実行
    asyncio.run(mcp.call_tool("search_docs", {"source": "sample", "format": "json"}))
    # 検証
    assert seen == [True]
    assert handlers.gate.active is False


def test_build_docs_mcp_when_error(
    make_mcp_handlers: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """エラーの変換（正常系）。"""

    # 準備
    def failing_write_docs(*args: Any, **kwargs: Any) -> Any:
        raise UnknownKindError(message="種類がありません", kinds=["rules"])

    monkeypatch.setattr(docs_module, "write_docs", failing_write_docs)
    mcp = build_docs_mcp(make_mcp_handlers())
    arguments: dict[str, Any] = {"operations": [{"op": "create", "kind": "x", "data": {}}]}
    # 実行
    result = asyncio.run(mcp.call_tool("write_docs", arguments))
    # 検証
    assert isinstance(result, CallToolResult)
    assert result.is_error is True
    assert isinstance(result.content[0], TextContent)
    assert "UnknownKindError" in result.content[0].text


def test_build_docs_mcp_when_descriptions(
    make_mcp_handlers: Callable[..., Any], bundled_prompts: Any
) -> None:
    """ツールの説明をプロンプトの YAML から描画する（正常系）。"""
    # 準備
    mcp = build_docs_mcp(make_mcp_handlers())
    # 実行
    tools = asyncio.run(mcp.list_tools())
    # 検証
    by_name = {tool.name: tool for tool in tools}
    assert {name: tool.description for name, tool in by_name.items()} == {
        name: bundled_prompts.render(tool_prompt_id("project-index", name)) for name in TOOL_NAMES
    }
    search_description = by_name["search_docs"].description or ""
    for word in (
        "not",
        "glob",
        "@matches",
        "sections",
        "lines",
        "describe(source, kind)",
        "group_by: tags",
    ):
        assert word in search_description
    assert "contains" in (by_name["list_changes"].description or "")
    assert "describe(source, kind)" in (by_name["write_docs"].description or "")
    assert "implements" in (by_name["trace_related"].description or "")
    search_properties = by_name["search_docs"].input_schema["properties"]
    changes_properties = by_name["list_changes"].input_schema["properties"]
    assert "description" in search_properties["sections"]
    assert "description" in search_properties["lines"]
    assert "description" in changes_properties["contains"]


def test_build_docs_mcp_when_loading(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """ツールの呼び出しは読み込みを待ち、スレッドを持たない（正常系）。"""
    # 準備
    config = make_source_dir("sample")
    terminal = make_terminal_config(sources=[make_entry(str(config), source_id="sample")])
    registry = SourceRegistry(loading=True)
    handlers = dataclasses.replace(build_handlers(terminal), registry=registry)
    mcp = build_docs_mcp(handlers)
    observed: dict[str, Any] = {}

    async def scenario() -> list[Any]:
        calls = [
            asyncio.ensure_future(
                mcp.call_tool(
                    "search_docs",
                    {"source": "sample", "format": "json", "cwd": str(config.parent)},
                )
            )
            for _ in range(13)
        ]
        observed["tools"] = await asyncio.wait_for(mcp.list_tools(), timeout=5)
        await asyncio.sleep(0.1)
        observed["done_before"] = [call.done() for call in calls]
        observed["executor_threads"] = [
            thread.name for thread in threading.enumerate() if thread.name.startswith("asyncio_")
        ]
        await asyncio.to_thread(registry.reload, terminal)
        return await asyncio.wait_for(asyncio.gather(*calls), timeout=30)

    # 実行
    results = asyncio.run(scenario())
    # 検証
    assert {tool.name for tool in observed["tools"]} == TOOL_NAMES
    assert observed["done_before"] == [False] * 13
    assert observed["executor_threads"] == []
    assert len(results) == 13
    assert all(isinstance(result, CallToolResult) and not result.is_error for result in results)


def _counter(*values: str) -> Callable[[], str]:
    """呼ぶたびに `values` を順に返す描画の関数を返す。"""
    pending = list(values)

    def _next() -> str:
        return pending.pop(0)

    return _next


def test_docs_mcp_server_when_initialize() -> None:
    """`initialize` のたびに描き直す（正常系）。"""
    from mcp import Client

    # 準備
    mcp = DocsMCPServer("project-index", instructions=_counter("v1", "v2", "v3"))

    async def _initialize() -> tuple[str | None, list[str]]:
        async with Client(mcp, mode="legacy") as client:
            tools = [tool.name for tool in (await client.list_tools()).tools]
            return client.instructions, tools

    # 実行
    first, first_tools = asyncio.run(_initialize())
    second, second_tools = asyncio.run(_initialize())
    # 検証
    assert first == "v2"
    assert second == "v3"
    assert first_tools == second_tools


def test_docs_mcp_server_when_discover() -> None:
    """`server/discover` のたびに描き直す（正常系）。"""
    from mcp import Client

    # 準備
    mcp = DocsMCPServer("project-index", instructions=_counter("v1", "v2", "v3"))

    async def _discover() -> tuple[str | None, str]:
        async with Client(mcp) as client:
            return client.instructions, client.protocol_version

    # 実行
    first, first_version = asyncio.run(_discover())
    second, _ = asyncio.run(_discover())
    # 検証
    assert first_version == "2026-07-28"
    assert first == "v2"
    assert second == "v3"


def _guided_registry(
    make_registry: Callable[..., Any],
    make_served_source: Callable[..., Any],
    make_source_config: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
    guides: list[tuple[str, list[str]]],
) -> tuple[Any, list[list[str]]]:
    """`(ID, when)` の配信元を並べた配信元の一覧の偽物と、裏の確認を依頼された ID の記録を返す。"""
    sources = [
        make_served_source(id=source_id, config=make_source_config(when=when))
        for source_id, when in guides
    ]
    registry = make_registry(*sources)
    requested: list[list[str]] = []

    def fake_refresh_later(source_ids: Sequence[str]) -> list[threading.Thread]:
        requested.append(list(source_ids))
        return []

    monkeypatch.setattr(registry, "refresh_later", fake_refresh_later)
    return registry, requested


def test_docs_instructions(
    make_mcp_handlers: Callable[..., Any],
    make_registry: Callable[..., Any],
    make_served_source: Callable[..., Any],
    make_source_config: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """使う場面を持つ配信元を端末の設定の順に並べる（正常系）。"""
    # 準備
    registry, requested = _guided_registry(
        make_registry,
        make_served_source,
        make_source_config,
        monkeypatch,
        [
            ("other", ["別の配信元を引くとき"]),
            ("sample", ["規約を確かめるとき", "設計書を書く前"]),
            ("old", []),
        ],
    )
    handlers = make_mcp_handlers(registry=registry)
    # 実行
    text = docs_module._docs_instructions(handlers)  # pyright: ignore[reportPrivateUsage]
    # 検証
    assert "`other`: 別の配信元を引くとき" in text
    assert "`sample`: 規約を確かめるとき" in text
    assert text.index("`other`") < text.index("`sample`")
    assert "設計書を書く前" not in text
    assert "`old`" not in text
    assert requested == [["other", "sample"]]


def test_docs_instructions_when_exceeds_limit(
    make_mcp_handlers: Callable[..., Any],
    make_registry: Callable[..., Any],
    make_served_source: Callable[..., Any],
    make_source_config: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上限を超える配信元を末尾から除く（正常系）。"""
    # 準備
    guides = [(f"src{index:02d}", ["あ" * 200]) for index in range(1, 31)]
    registry, _ = _guided_registry(
        make_registry, make_served_source, make_source_config, monkeypatch, guides
    )
    handlers = make_mcp_handlers(registry=registry)
    # 実行
    text = docs_module._docs_instructions(handlers)  # pyright: ignore[reportPrivateUsage]
    # 検証
    listed = re.findall(r"`(src\d{2})`", text)
    assert len(text) <= INSTRUCTIONS_MAX_CHARS
    assert 0 < len(listed) < 30
    assert listed == [f"src{index:02d}" for index in range(1, len(listed) + 1)]
    assert f"{30 - len(listed)} 件" in text
    assert "describe(outside_scope: true)" in text


def test_docs_instructions_when_no_source_guide(
    make_mcp_handlers: Callable[..., Any],
    make_registry: Callable[..., Any],
    make_served_source: Callable[..., Any],
    make_source_config: Callable[..., Any],
    bundled_prompts: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """使う場面を持つ配信元が無い（正常系）。"""
    # 準備
    registry, _ = _guided_registry(
        make_registry, make_served_source, make_source_config, monkeypatch, [("old", [])]
    )
    handlers = make_mcp_handlers(registry=registry)
    # 実行
    text = docs_module._docs_instructions(handlers)  # pyright: ignore[reportPrivateUsage]
    # 検証
    assert text == bundled_prompts.render(
        DOCS_INSTRUCTIONS_PROMPT_ID, {"sources": [], "omitted": 0}
    )


def test_wait_target() -> None:
    """要求ごとの待つ行の決め方（正常系）。"""
    # 準備
    from project_index.features.describe.types import DescribeRequest
    from project_index.features.write.types import WriteRequest

    requests = [
        SearchRequest(source="a"),
        SearchRequest(source=["a", "*"]),
        DescribeRequest(outside_scope=True),
        WriteRequest(cwd="/w/a", operations=[]),
        DescribeRequest(),
    ]
    # 実行
    targets = [docs_module._wait_target(request) for request in requests]
    # 検証
    assert targets == [
        {"ids": ["a"]},
        {"every": True},
        {"every": True},
        {"cwd": "/w/a"},
        {},
    ]


def test_build_docs_mcp_when_unexpected_error(
    make_mcp_handlers: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """想定外の例外を isError にする（正常系）。"""

    # 準備
    def failing_search_docs(*args: Any, **kwargs: Any) -> Any:
        raise GitError(["archive", "abc"], -1, "20 秒を超えたため止めました", timed_out=True)

    monkeypatch.setattr(docs_module, "search_docs", failing_search_docs)
    caplog.set_level(logging.ERROR, logger=docs_module.__name__)
    mcp = build_docs_mcp(make_mcp_handlers())
    # 実行
    result = asyncio.run(mcp.call_tool("search_docs", {"source": "sample"}))
    # 検証
    assert isinstance(result, CallToolResult)
    assert result.is_error is True
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text.startswith("UnexpectedError: GitError:")
    assert "ツールの処理に失敗した（search_docs）" in caplog.text
    assert "Traceback" in caplog.text


def test_build_docs_mcp_when_limits(
    make_mcp_handlers: Callable[..., Any],
    make_terminal_config: Callable[..., TerminalConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """書き込みに呼び出しの期限を渡す（正常系）。"""
    # 準備
    received: list[CallLimits] = []

    def recording_write_docs(request: WriteRequest, **kwargs: Any) -> WriteResult:
        received.append(kwargs["limits"])
        return WriteResult(applied=False, results=[])

    monkeypatch.setattr(docs_module, "write_docs", recording_write_docs)
    handlers = make_mcp_handlers(terminal=make_terminal_config(write_deadline_sec=32))
    mcp = build_docs_mcp(handlers)
    arguments: dict[str, Any] = {"operations": [{"op": "create", "kind": "x", "data": {}}]}
    # 実行
    asyncio.run(mcp.call_tool("write_docs", arguments))
    # 検証
    assert received[0].write_deadline.limit_sec == 32
    assert received[0].respond_by.limit_sec == TOOL_RESPONSE_LIMIT_SEC


def _worktree_target(
    tmp_path: Path,
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
) -> Target:
    """ワークツリー x を指す読み書きの場所を作る。"""
    worktree = tmp_path / "clone" / ".claude" / "worktrees" / "x"
    source = make_served_source(id="sample", root=tmp_path / "clone")
    return make_target(source, base=worktree, worktree=worktree)


def _fake_store(*, loaded: bool, release: threading.Event | None = None) -> Any:
    """読み込み済みかを決めた文書のストアの偽物（`load` の呼び出しを記録し、`release` まで止まる）。"""
    calls: list[Any] = []

    def load(target: Any) -> None:
        calls.append(target)
        if release is not None:
            release.wait(timeout=10)

    return SimpleNamespace(has_worktree=_answer(loaded), load=load, calls=calls)


def _answer(value: bool) -> Callable[[object], bool]:
    """いつも `value` を返す、読み込み済みかの判定の偽物。"""

    def _fixed(target: object) -> bool:
        return value

    return _fixed


def _returning(value: object) -> Callable[..., object]:
    """キーワード引数を受けていつも `value` を返す、場所の解決の偽物。"""

    def _fixed(**kwargs: object) -> object:
        return value

    return _fixed


def test_ensure_worktree(
    tmp_path: Path,
    make_mcp_handlers: Callable[..., Any],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """初めての読み込みを待つ（正常系）。"""
    # 準備
    target = _worktree_target(tmp_path, make_served_source, make_target)
    monkeypatch.setattr(docs_module, "resolve_read_targets", _returning([target]), raising=False)
    store = _fake_store(loaded=False)
    handlers = make_mcp_handlers(store=store)
    loads: dict[Path, Any] = {}

    async def scenario() -> None:
        await docs_module._ensure_worktree(SearchRequest(source="sample"), handlers, loads)  # pyright: ignore[reportPrivateUsage]
        await asyncio.sleep(0)

    # 実行
    asyncio.run(scenario())
    # 検証
    assert store.calls == [target]
    assert loads == {}


def test_ensure_worktree_when_loaded(
    tmp_path: Path,
    make_mcp_handlers: Callable[..., Any],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """読み込み済みのワークツリーは待たない（正常系）。"""
    # 準備
    target = _worktree_target(tmp_path, make_served_source, make_target)
    monkeypatch.setattr(docs_module, "resolve_read_targets", _returning([target]), raising=False)
    store = _fake_store(loaded=True)
    handlers = make_mcp_handlers(store=store)
    # 実行
    asyncio.run(docs_module._ensure_worktree(SearchRequest(source="sample"), handlers, {}))  # pyright: ignore[reportPrivateUsage]
    # 検証
    assert store.calls == []


def test_ensure_worktree_when_slow(
    tmp_path: Path,
    make_mcp_handlers: Callable[..., Any],
    make_terminal_config: Callable[..., TerminalConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上限までに終わらない読み込み（異常系）。"""
    # 準備
    target = _worktree_target(tmp_path, make_served_source, make_target)
    monkeypatch.setattr(docs_module, "resolve_read_targets", _returning([target]), raising=False)
    release = threading.Event()
    store = _fake_store(loaded=False, release=release)
    handlers = make_mcp_handlers(
        store=store, terminal=make_terminal_config(worktree_load_wait_sec=1)
    )
    loads: dict[Path, Any] = {}
    request = SearchRequest(source="sample")
    ensure = docs_module._ensure_worktree  # pyright: ignore[reportPrivateUsage]

    async def scenario() -> list[BaseException | None]:
        first = await asyncio.gather(ensure(request, handlers, loads), return_exceptions=True)
        second = await asyncio.gather(ensure(request, handlers, loads), return_exceptions=True)
        release.set()
        await asyncio.gather(*loads.values(), return_exceptions=True)
        store.has_worktree = _answer(True)
        third = await asyncio.gather(ensure(request, handlers, loads), return_exceptions=True)
        return [first[0], second[0], third[0]]

    # 実行
    results = asyncio.run(scenario())
    # 検証
    assert isinstance(results[0], WorktreeLoadingError)
    assert isinstance(results[1], WorktreeLoadingError)
    assert results[2] is None
    assert store.calls == [target]


def test_ensure_worktree_when_write(
    tmp_path: Path,
    make_mcp_handlers: Callable[..., Any],
    make_terminal_config: Callable[..., TerminalConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """書き込みでも初めての読み込みを上限まで待つ（異常系）。"""
    # 準備
    target = _worktree_target(tmp_path, make_served_source, make_target)
    monkeypatch.setattr(docs_module, "resolve_write_target", _returning(target), raising=False)
    release = threading.Event()
    store = _fake_store(loaded=False, release=release)
    handlers = make_mcp_handlers(
        store=store, terminal=make_terminal_config(worktree_load_wait_sec=1)
    )
    loads: dict[Path, Any] = {}
    request = WriteRequest(operations=[])
    ensure = docs_module._ensure_worktree  # pyright: ignore[reportPrivateUsage]

    async def scenario() -> BaseException | None:
        result = await asyncio.gather(ensure(request, handlers, loads), return_exceptions=True)
        release.set()
        await asyncio.gather(*loads.values(), return_exceptions=True)
        return result[0]

    # 実行
    result = asyncio.run(scenario())
    # 検証
    assert isinstance(result, WorktreeLoadingError)
    assert store.calls == [target]


def test_ensure_worktree_when_reload_slow(
    tmp_path: Path,
    make_mcp_handlers: Callable[..., Any],
    make_terminal_config: Callable[..., TerminalConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ワークツリーの設定の再読み込みも待ちの上限の内で待つ（異常系）。"""
    # 準備
    target = _worktree_target(tmp_path, make_served_source, make_target)
    release = threading.Event()
    reloads: list[object] = []

    def slow_reload(**kwargs: object) -> list[Target]:
        reloads.append(kwargs.get("reload_worktree", True))
        # 再読み込みつきの解決だけ、合図するまで終わらない
        if kwargs.get("reload_worktree", True):
            release.wait(timeout=10)
        return [target]

    monkeypatch.setattr(docs_module, "resolve_read_targets", slow_reload, raising=False)
    store = _fake_store(loaded=False)
    handlers = make_mcp_handlers(
        store=store, terminal=make_terminal_config(worktree_load_wait_sec=1)
    )
    loads: dict[Path, Any] = {}
    ensure = docs_module._ensure_worktree  # pyright: ignore[reportPrivateUsage]

    async def scenario() -> tuple[BaseException | None, float]:
        started = time.monotonic()
        result = await asyncio.gather(
            ensure(SearchRequest(source="sample"), handlers, loads), return_exceptions=True
        )
        elapsed = time.monotonic() - started
        release.set()
        await asyncio.gather(*loads.values(), return_exceptions=True)
        return result[0], elapsed

    # 実行
    result, elapsed = asyncio.run(scenario())
    # 検証
    assert isinstance(result, WorktreeLoadingError)
    assert elapsed < 3
    assert reloads == [False, True]


def test_ensure_worktree_when_unresolved(
    make_mcp_handlers: Callable[..., Any],
) -> None:
    """場所を解けない要求は待たずにサービスへ渡す（正常系）。"""
    # 準備
    store = _fake_store(loaded=False)
    handlers = make_mcp_handlers(store=store)
    # 実行
    asyncio.run(docs_module._ensure_worktree(SearchRequest(source="sample"), handlers, {}))  # pyright: ignore[reportPrivateUsage]
    # 検証
    assert store.calls == []

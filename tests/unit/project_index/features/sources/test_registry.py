from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from project_index.features.settings.types import SourceEntry, TerminalConfig
from project_index.features.sources import registry as registry_module
from project_index.features.sources.registry import SourceRegistry
from project_index.features.sources.schema_ref import SchemaRefLookup
from project_index.features.sources.types import ServedSource, SourceStatus
from project_index.shared.errors import SourceNotServedError, UnknownSourceError, Violation

type LoadResult = tuple[ServedSource | None, SourceStatus]


def test_source_registry_reload(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """状態を行の順に返す（正常系）。"""
    # 準備
    results: list[LoadResult] = [
        (make_served_source(id="a"), make_status("a", 0)),
        (
            None,
            make_status(
                "b",
                1,
                "not_served",
                errors=[Violation(path="documents[0].paths", rule="必須のキーが無い")],
            ),
        ),
        (None, make_status("c", 2, "disabled")),
    ]
    monkeypatch.setattr(
        registry_module, "load_source", lambda entry, *, index, lookup=None: results[index]
    )
    terminal = make_terminal_config(
        sources=[make_entry(f"/tmp/{name}/project-index.yaml", source_id=name) for name in "abc"]
    )
    registry = SourceRegistry()
    # 実行
    statuses = registry.reload(terminal)
    # 検証
    assert [status.status for status in statuses] == ["serving", "not_served", "disabled"]
    assert len(registry.served()) == 1


def test_source_registry_reload_when_duplicate_name(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """既定の ID が重なる（正常系）。"""
    # 準備
    monkeypatch.setattr(
        registry_module,
        "load_source",
        lambda entry, *, index, lookup=None: (make_served_source(id="a"), make_status("a", index)),
    )
    terminal = make_terminal_config(
        sources=[make_entry("/tmp/x/project-index.yaml"), make_entry("/tmp/y/project-index.yaml")]
    )
    registry = SourceRegistry()
    # 実行
    statuses = registry.reload(terminal)
    # 検証
    assert statuses[1].status == "not_served"
    assert [error.path for error in statuses[1].errors] == ["sources[1].id"]
    assert [error.rule for error in statuses[1].errors] == ["a は既に使用されています"]


def test_source_registry_reload_when_reading(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """読み直しの間は古い一覧で応える（正常系）。"""
    # 準備
    old = make_served_source(id="a", root=tmp_path / "old")
    new = make_served_source(id="a", root=tmp_path / "new")
    entered = threading.Event()
    release = threading.Event()
    served: list[ServedSource] = [old, new]

    def blocking_load(entry: SourceEntry, *, index: int, lookup: object = None) -> LoadResult:
        source = served.pop(0)
        if source is new:
            entered.set()
            release.wait(timeout=5)
        return source, make_status("a", index)

    monkeypatch.setattr(registry_module, "load_source", blocking_load)
    terminal = make_terminal_config(sources=[make_entry("/tmp/a/project-index.yaml", source_id="a")])
    registry = SourceRegistry()
    registry.reload(terminal)
    worker = threading.Thread(target=registry.reload, args=(terminal,))
    worker.start()
    entered.wait(timeout=5)
    # 実行
    during = registry.get("a")
    release.set()
    worker.join(timeout=5)
    after = registry.get("a")
    # 検証
    assert during.root == tmp_path / "old"
    assert after.root == tmp_path / "new"


def test_source_registry_get(
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """配信中を引く（正常系）。"""
    # 準備
    registry = SourceRegistry()
    source = make_served_source(id="a")
    registry._snapshot = ({"a": source}, [make_status("a", 0)])
    # 実行
    result = registry.get("a")
    # 検証
    assert result is source


def test_source_registry_get_when_not_served(
    make_status: Callable[..., SourceStatus],
) -> None:
    """外した配信元（異常系）。"""
    # 準備
    registry = SourceRegistry()
    errors = [Violation(path="documents[0].paths", rule="必須のキーが無い")]
    registry._snapshot = ({}, [make_status("b", 0, "not_served", errors=errors)])
    # 実行・検証
    with pytest.raises(SourceNotServedError) as exc_info:
        registry.get("b")
    assert exc_info.value.violations == errors
    assert exc_info.value.disabled is False


def test_source_registry_get_when_unknown() -> None:
    """無い配信元（異常系）。"""
    # 準備
    registry = SourceRegistry()
    # 実行・検証
    with pytest.raises(UnknownSourceError):
        registry.get("z")


def test_source_registry_get_when_default_ref_moved(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    sample_files: dict[str, str],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """default_ref が進んだら組み立て直す（正常系）。"""
    # 準備
    root = git_repo(sample_files)
    terminal = make_terminal_config(
        sources=[make_entry(str(root / "project-index.yaml"), source_id="a")]
    )
    registry = SourceRegistry()
    registry.reload(terminal)
    commit_all(
        root,
        {
            "project-index.yaml": sample_files["project-index.yaml"]
            + "  - id: kind_a\n    paths: [docs/a/*.yaml]\n    schema: schemas/a.schema.yaml\n",
            "schemas/a.schema.yaml": "title: a\ntype: object\n",
        },
    )
    # 実行
    first = registry.get("a")
    second = registry.get("a")
    # 検証
    assert [table.id for table in first.config.documents] == ["rules", "kind_a"]
    assert second is first


def test_source_registry_get_when_default_ref_moved_with_on_rebuilt(
    git_repo: Callable[..., Path],
    commit_all: Callable[..., str],
    sample_files: dict[str, str],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """組み立て直した後の処理を呼ぶ（正常系）。"""
    # 準備
    root = git_repo(sample_files)
    terminal = make_terminal_config(
        sources=[make_entry(str(root / "project-index.yaml"), source_id="a")]
    )
    rebuilt: list[ServedSource] = []
    registry = SourceRegistry(on_rebuilt=rebuilt.append)
    registry.reload(terminal)
    commit_all(
        root,
        {
            "project-index.yaml": sample_files["project-index.yaml"]
            + "  - id: kind_a\n    paths: [docs/a/*.yaml]\n    schema: schemas/a.schema.yaml\n",
            "schemas/a.schema.yaml": "title: a\ntype: object\n",
        },
    )
    # 実行
    first = registry.get("a")
    registry.get("a")
    # 検証
    assert rebuilt == [first]


def test_source_registry_reload_when_loading(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """初回の読み込みまで wait_loaded を待たせ、スレッドは持たない（正常系）。"""
    # 準備
    entered = threading.Event()
    release = threading.Event()

    def blocking_load(entry: SourceEntry, *, index: int, lookup: object = None) -> LoadResult:
        entered.set()
        release.wait(timeout=5)
        return make_served_source(id="a"), make_status("a", index)

    monkeypatch.setattr(registry_module, "load_source", blocking_load)
    terminal = make_terminal_config(sources=[make_entry("/tmp/a/project-index.yaml", source_id="a")])
    registry = SourceRegistry(loading=True)
    observed: dict[str, object] = {}

    async def scenario() -> None:
        waiters = [asyncio.ensure_future(registry.wait_loaded()) for _ in range(2)]
        await asyncio.sleep(0)
        worker = threading.Thread(target=registry.reload, args=(terminal,))
        worker.start()
        await asyncio.to_thread(entered.wait, 5)
        await asyncio.sleep(0.05)
        observed["loading_before"] = registry.loading
        observed["done_before"] = [waiter.done() for waiter in waiters]
        observed["statuses_before"] = registry.statuses()
        observed["served_before"] = registry.served()
        release.set()
        await asyncio.wait_for(asyncio.gather(*waiters), timeout=5)
        await asyncio.to_thread(worker.join, 5)

    # 実行
    asyncio.run(scenario())
    # 検証
    assert observed["loading_before"] is True
    assert observed["done_before"] == [False, False]
    assert observed["statuses_before"] == []
    assert observed["served_before"] == []
    assert registry.get("a").id == "a"
    assert len(registry.served()) == 1
    assert registry.loading is False


def test_source_registry_reload_when_failed(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """読み込みが例外で止まっても待ちを解く（異常系）。"""

    # 準備
    def failing_load(entry: SourceEntry, *, index: int, lookup: object = None) -> LoadResult:
        raise RuntimeError("読めない")

    monkeypatch.setattr(registry_module, "load_source", failing_load)
    terminal = make_terminal_config(sources=[make_entry("/tmp/a/project-index.yaml", source_id="a")])
    registry = SourceRegistry(loading=True)
    errors: list[BaseException] = []

    def reload_in_thread() -> None:
        try:
            registry.reload(terminal)
        except RuntimeError as error:
            errors.append(error)

    async def scenario() -> None:
        waiter = asyncio.ensure_future(registry.wait_loaded())
        await asyncio.sleep(0)
        await asyncio.to_thread(reload_in_thread)
        await asyncio.wait_for(waiter, timeout=5)

    # 実行
    asyncio.run(scenario())
    # 検証
    assert [str(error) for error in errors] == ["読めない"]
    assert registry.loading is False
    assert registry.served() == []


class _Loader:
    """名前ごとに結果を返し、読んだ順を記録し、指定した名前で止まる配信元の読み込みの偽物。"""

    def __init__(
        self,
        make_served_source: Callable[..., ServedSource],
        make_status: Callable[..., SourceStatus],
        *,
        blocked: tuple[str, ...] = (),
        failing: tuple[str, ...] = (),
        names: dict[str, str] | None = None,
    ) -> None:
        self.order: list[str] = []
        self.lookups: list[SchemaRefLookup] = []
        self.entered = {name: threading.Event() for name in blocked}
        self.release = {name: threading.Event() for name in blocked}
        self._failing = failing
        self._names = names or {}
        self._make_served_source = make_served_source
        self._make_status = make_status

    def __call__(self, entry: SourceEntry, *, index: int, lookup: SchemaRefLookup) -> LoadResult:
        # 設定のパス `/tmp/{名前}/project-index.yaml` から名前を取る
        name = Path(entry.config[0]).parent.name
        self.order.append(name)
        self.lookups.append(lookup)
        if name in self.entered:
            self.entered[name].set()
            self.release[name].wait(timeout=5)
        if name in self._failing:
            raise RuntimeError(f"{name} を読めない")
        source_id = entry.id or self._names.get(name, name)
        return (
            self._make_served_source(id=source_id, root=Path("/tmp") / name),
            self._make_status(source_id, index),
        )


def _entries(
    make_entry: Callable[..., SourceEntry], *names: str, with_id: bool = True
) -> list[SourceEntry]:
    """名前ごとに `/tmp/{名前}/project-index.yaml` を読む行を作る。"""
    return [
        make_entry(f"/tmp/{name}/project-index.yaml", source_id=name if with_id else None)
        for name in names
    ]


def test_source_registry_load(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """行ごとに読み込み、全ての行を読み込むと読み込み中が終わる（正常系）。"""
    # 準備
    results: list[LoadResult] = [
        (make_served_source(id="a"), make_status("a", 0)),
        (make_served_source(id="b"), make_status("b", 1)),
        (None, make_status("c", 2, "disabled")),
    ]
    monkeypatch.setattr(
        registry_module, "load_source", lambda entry, *, index, lookup: results[index]
    )
    terminal = make_terminal_config(sources=_entries(make_entry, "a", "b", "c"))
    registry = SourceRegistry(loading=True)
    # 実行
    registry.load(terminal)
    # 検証
    assert registry.loading is False
    assert [(status.id, status.status) for status in registry.statuses()] == [
        ("a", "serving"),
        ("b", "serving"),
        ("c", "disabled"),
    ]
    assert len(registry.served()) == 2


def test_source_registry_load_when_schema_ref(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """行ごとの読み込みに、端末の設定から作ったほかの配信元の引き当てを渡す（正常系）。"""
    # 準備
    loader = _Loader(make_served_source, make_status)
    monkeypatch.setattr(registry_module, "load_source", loader)
    terminal = make_terminal_config(sources=_entries(make_entry, "a", "b"))
    registry = SourceRegistry(loading=True)
    # 実行
    registry.load(terminal)
    # 検証
    assert len(loader.lookups) == 2
    assert loader.lookups[0] is loader.lookups[1]
    assert loader.lookups[0]("b") == Path("/tmp/b/project-index.yaml")
    assert loader.lookups[0]("missing") is None


def test_source_registry_load_when_lookup_failed(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """引き当ての作成が例外で止まっても、待ちを解いて読み込み中を終える（異常系）。"""
    # 準備

    def failing_lookup(terminal: TerminalConfig) -> SchemaRefLookup:
        raise RuntimeError("引き当てを作れない")

    monkeypatch.setattr(registry_module, "terminal_lookup", failing_lookup)
    terminal = make_terminal_config(sources=_entries(make_entry, "a"))
    registry = SourceRegistry(loading=True)
    errors: list[BaseException] = []

    def work() -> None:
        try:
            registry.load(terminal)
        except RuntimeError as error:
            errors.append(error)

    async def scenario() -> None:
        waiter = asyncio.ensure_future(registry.wait_loaded())
        worker = threading.Thread(target=work)
        worker.start()
        await asyncio.wait_for(waiter, timeout=5)
        await asyncio.to_thread(worker.join, 5)

    # 実行
    asyncio.run(scenario())
    # 検証
    assert registry.loading is False
    assert [str(error) for error in errors] == ["引き当てを作れない"]


def test_source_registry_load_when_row_loading(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """読み込んだ行は、他の行の読み込み中でも引ける（正常系）。"""
    # 準備
    loader = _Loader(make_served_source, make_status, blocked=("b",))
    monkeypatch.setattr(registry_module, "load_source", loader)
    terminal = make_terminal_config(sources=_entries(make_entry, "a", "b"))
    registry = SourceRegistry(loading=True)
    worker = threading.Thread(target=registry.load, args=(terminal,))
    worker.start()
    loader.entered["b"].wait(timeout=5)
    # 実行
    result = registry.get("a")
    loading = registry.loading
    loader.release["b"].set()
    worker.join(timeout=5)
    # 検証
    assert result.id == "a"
    assert loading is True


def test_source_registry_load_when_requested(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """待っている要求が指す行を先に読み込む（正常系）。"""
    # 準備
    loader = _Loader(make_served_source, make_status, blocked=("a", "b"))
    monkeypatch.setattr(registry_module, "load_source", loader)
    terminal = make_terminal_config(sources=_entries(make_entry, "a", "b", "c"))
    waiting = threading.Event()
    registry = SourceRegistry(loading=True, on_waiting=waiting.set)
    observed: dict[str, object] = {}

    async def scenario() -> None:
        worker = threading.Thread(target=registry.load, args=(terminal,))
        worker.start()
        await asyncio.to_thread(loader.entered["a"].wait, 5)
        waiter = asyncio.ensure_future(registry.wait_for(ids=["c"]))
        await asyncio.to_thread(waiting.wait, 5)
        loader.release["a"].set()
        await asyncio.wait_for(waiter, timeout=5)
        # b は止めてあるので、待ちが済んだ時点で b の読み込みは終わっていない
        observed["b_loaded_when_done"] = registry.loading is False
        loader.release["b"].set()
        await asyncio.to_thread(worker.join, 5)

    # 実行
    asyncio.run(scenario())
    # 検証
    assert loader.order == ["a", "c", "b"]
    assert observed["b_loaded_when_done"] is False


def test_source_registry_load_when_row_failed(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """行の読み込みが例外で止まっても、その行を配信せずに残りの行を読み込む（異常系）。"""
    # 準備
    loader = _Loader(make_served_source, make_status, failing=("broken",))
    monkeypatch.setattr(registry_module, "load_source", loader)
    terminal = make_terminal_config(sources=_entries(make_entry, "broken", "sample"))
    registry = SourceRegistry(loading=True)

    async def scenario() -> None:
        waiter = asyncio.ensure_future(registry.wait_for(ids=["broken"]))
        await asyncio.sleep(0)
        await asyncio.to_thread(registry.load, terminal)
        await asyncio.wait_for(waiter, timeout=5)

    # 実行
    asyncio.run(scenario())
    # 検証
    with pytest.raises(SourceNotServedError) as exc_info:
        registry.get("broken")
    assert [error.path for error in exc_info.value.violations] == ["sources[0]"]
    assert registry.get("sample").id == "sample"
    assert registry.loading is False


def test_source_registry_load_when_duplicate_loaded_later(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """後の行が先に読み込まれて ID が重なる（正常系）。"""
    # 準備
    from project_index.features.settings.types import SourceScope

    loader = _Loader(make_served_source, make_status, blocked=("z",), names={"x": "a", "y": "a"})
    monkeypatch.setattr(registry_module, "load_source", loader)
    terminal = make_terminal_config(
        sources=[
            make_entry("/tmp/z/project-index.yaml", source_id="z"),
            make_entry("/tmp/x/project-index.yaml", scope=SourceScope(read=["/w/x/**"])),
            make_entry("/tmp/y/project-index.yaml", scope=SourceScope(read=["/w/y/**"])),
        ]
    )
    waiting = threading.Event()
    registry = SourceRegistry(loading=True, on_waiting=waiting.set)

    async def scenario() -> None:
        worker = threading.Thread(target=registry.load, args=(terminal,))
        worker.start()
        await asyncio.to_thread(loader.entered["z"].wait, 5)
        waiter = asyncio.ensure_future(registry.wait_for(cwd="/w/y/q"))
        await asyncio.to_thread(waiting.wait, 5)
        loader.release["z"].set()
        await asyncio.wait_for(waiter, timeout=5)
        await asyncio.to_thread(worker.join, 5)

    # 実行
    asyncio.run(scenario())
    # 検証
    assert loader.order == ["z", "y", "x"]
    statuses = registry.statuses()
    assert [status.status for status in statuses] == ["serving", "serving", "not_served"]
    assert [error.path for error in statuses[2].errors] == ["sources[2].id"]
    assert registry.get("a").root == Path("/tmp/x")


def test_source_registry_wait_for(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """指す行の読み込みだけを待つ（正常系）。"""
    # 準備
    loader = _Loader(make_served_source, make_status, blocked=("b",))
    monkeypatch.setattr(registry_module, "load_source", loader)
    terminal = make_terminal_config(sources=_entries(make_entry, "a", "b"))
    registry = SourceRegistry(loading=True)
    observed: dict[str, object] = {}

    async def scenario() -> None:
        worker = threading.Thread(target=registry.load, args=(terminal,))
        worker.start()
        await asyncio.to_thread(loader.entered["b"].wait, 5)
        await asyncio.wait_for(registry.wait_for(ids=["a"]), timeout=5)
        waiter_b = asyncio.ensure_future(registry.wait_for(ids=["b"]))
        await asyncio.sleep(0.05)
        observed["b_before"] = waiter_b.done()
        loader.release["b"].set()
        await asyncio.wait_for(waiter_b, timeout=5)
        await asyncio.to_thread(worker.join, 5)

    # 実行
    asyncio.run(scenario())
    # 検証
    assert observed["b_before"] is False


def test_source_registry_wait_for_when_cwd(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """作業場所が scope に当たる行を待つ（正常系）。"""
    # 準備
    from project_index.features.settings.types import SourceScope

    loader = _Loader(make_served_source, make_status, blocked=("b",))
    monkeypatch.setattr(registry_module, "load_source", loader)
    terminal = make_terminal_config(
        sources=[
            make_entry("/tmp/a/project-index.yaml", source_id="a", scope=SourceScope(read=["/w/a/**"])),
            make_entry("/tmp/b/project-index.yaml", source_id="b", scope=SourceScope(read=["/w/b/**"])),
        ]
    )
    registry = SourceRegistry(loading=True)
    observed: dict[str, object] = {}

    async def scenario() -> None:
        worker = threading.Thread(target=registry.load, args=(terminal,))
        worker.start()
        await asyncio.to_thread(loader.entered["b"].wait, 5)
        await asyncio.wait_for(registry.wait_for(cwd="/w/a/x"), timeout=5)
        waiter_c = asyncio.ensure_future(registry.wait_for(cwd="/w/c"))
        await asyncio.sleep(0.05)
        observed["c_before"] = waiter_c.done()
        loader.release["b"].set()
        await asyncio.wait_for(waiter_c, timeout=5)
        await asyncio.to_thread(worker.join, 5)

    # 実行
    asyncio.run(scenario())
    # 検証
    assert observed["c_before"] is False


def test_source_registry_wait_for_when_id_less_row(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """ID を持たない行は、ID で指す要求でも待つ（正常系）。"""
    # 準備
    loader = _Loader(make_served_source, make_status, blocked=("m",), names={"m": "n"})
    monkeypatch.setattr(registry_module, "load_source", loader)
    terminal = make_terminal_config(
        sources=[
            make_entry("/tmp/a/project-index.yaml", source_id="a"),
            make_entry("/tmp/m/project-index.yaml"),
        ]
    )
    registry = SourceRegistry(loading=True)
    observed: dict[str, object] = {}

    async def scenario() -> None:
        worker = threading.Thread(target=registry.load, args=(terminal,))
        worker.start()
        await asyncio.to_thread(loader.entered["m"].wait, 5)
        waiter = asyncio.ensure_future(registry.wait_for(ids=["n"]))
        await asyncio.sleep(0.05)
        observed["before"] = waiter.done()
        loader.release["m"].set()
        await asyncio.wait_for(waiter, timeout=5)
        await asyncio.to_thread(worker.join, 5)

    # 実行
    asyncio.run(scenario())
    # 検証
    assert observed["before"] is False
    assert registry.get("n").id == "n"


def test_source_registry_wait_for_when_cancelled(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """取り消された待ちを外す（正常系）。"""
    # 準備
    loader = _Loader(make_served_source, make_status, blocked=("b",))
    monkeypatch.setattr(registry_module, "load_source", loader)
    terminal = make_terminal_config(sources=_entries(make_entry, "a", "b"))
    registry = SourceRegistry(loading=True)
    observed: dict[str, object] = {}

    async def scenario() -> None:
        worker = threading.Thread(target=registry.load, args=(terminal,))
        worker.start()
        await asyncio.to_thread(loader.entered["b"].wait, 5)
        task = asyncio.ensure_future(registry.wait_for(ids=["b"]))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            observed["cancelled"] = True
        observed["waiters"] = list(registry._waiters)
        loader.release["b"].set()
        await asyncio.to_thread(worker.join, 5)

    # 実行
    asyncio.run(scenario())
    # 検証
    assert observed["cancelled"] is True
    assert observed["waiters"] == []


def test_source_registry_get_when_row_loading(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
) -> None:
    """読み込んでいない行の ID を引くと、その行の読み込みを待つ（正常系）。"""
    # 準備
    loader = _Loader(make_served_source, make_status, blocked=("a",))
    monkeypatch.setattr(registry_module, "load_source", loader)
    terminal = make_terminal_config(sources=_entries(make_entry, "a", "b"))
    registry = SourceRegistry(loading=True)
    worker = threading.Thread(target=registry.load, args=(terminal,))
    worker.start()
    loader.entered["a"].wait(timeout=5)
    results: list[ServedSource] = []
    getter = threading.Thread(target=lambda: results.append(registry.get("b")))
    getter.start()
    getter.join(timeout=0.2)
    # 実行
    returned_before = bool(results)
    loader.release["a"].set()
    getter.join(timeout=5)
    worker.join(timeout=5)
    # 検証
    assert returned_before is False
    assert [source.id for source in results] == ["b"]
    assert loader.order == ["a", "b"]

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.convert import service as service_module
from project_index.features.convert.service import ConvertService
from project_index.features.documents.types import Document, LoadResult
from project_index.features.sources.types import (
    DocumentTable,
    ScriptEntry,
    ServedSource,
    SourceConfig,
)
from project_index.integrations.scripts import ScriptResult
from project_index.shared.errors import ConverterNotDefinedError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.access.types import Target


def _service(tmp_path: Path, schema: dict[str, Any], timeout_sec: float = 10) -> ConvertService:
    """決めたスキーマを返す文書のストアの偽物で、変換を作る。"""
    store = SimpleNamespace(
        schema=lambda target, kind: schema,
        row_schema=lambda target, kind: schema,
        load=lambda target: LoadResult(),
    )
    return ConvertService(tmp_path / "converted", store, timeout_sec)  # type: ignore[arg-type]


@pytest.fixture
def make_converted_target(
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
) -> Callable[..., Target]:
    """変換の設定を持つ文書の行の読み書きの場所を作る関数を返す。"""

    def _make(
        *, body_file: bool = False, converter: str | None = None, converters: list[ScriptEntry]
    ) -> Target:
        root = tmp_path / "ws"
        root.mkdir(exist_ok=True)
        table = DocumentTable(
            id="rules",
            paths=["rules/*.yaml"],
            schema_path="schemas/rule.schema.yaml",
            converter=converter,
            records="files" if body_file else None,
            body_file="path" if body_file else None,
        )
        config = make_source_config(documents=[table], converters=converters)
        return make_target(make_served_source(root=root, config=config))

    return _make


def test_convert_service_convert_when_converter_not_defined(
    tmp_path: Path,
    make_converted_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """converters[] を指さない種類を断る（異常系）。"""
    # 準備
    calls: list[list[str]] = []

    def fake_run_script(run: Any, **kwargs: Any) -> ScriptResult:
        calls.append(list(run))
        return ScriptResult(stdout="# 変換した\n", stderr="")

    monkeypatch.setattr(service_module, "run_script", fake_run_script)
    target = make_converted_target(converter=None, converters=[])
    service = _service(tmp_path, {})
    document = make_document()
    # 実行・検証
    with pytest.raises(ConverterNotDefinedError, match="converters"):
        service.convert(target, document)
    assert calls == []


def test_convert_service_convert_when_converter(
    tmp_path: Path,
    make_converted_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """スクリプトで変換し、2 回目は控えを使う（正常系）。"""
    # 準備
    calls: list[list[str]] = []

    def fake_run_script(run: Any, **kwargs: Any) -> ScriptResult:
        calls.append(list(run))
        return ScriptResult(stdout="# 変換した\n", stderr="")

    monkeypatch.setattr(service_module, "run_script", fake_run_script)
    target = make_converted_target(
        converter="c", converters=[ScriptEntry(id="c", run=["python3", "scripts/c.py"])]
    )
    service = _service(tmp_path, {})
    document = make_document()
    # 実行
    first = service.convert(target, document)
    second = service.convert(target, document)
    # 検証
    assert first.markdown.startswith("# 変換した")
    assert second.markdown.startswith("# 変換した")
    assert len(calls) == 1


def test_convert_service_convert_when_cache_disabled(
    tmp_path: Path,
    make_converted_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cache: false の変換は毎回スクリプトを動かし、控えを書かない（正常系）。"""
    # 準備
    calls: list[list[str]] = []

    def fake_run_script(run: Any, **kwargs: Any) -> ScriptResult:
        calls.append(list(run))
        return ScriptResult(stdout="# 変換した\n", stderr="")

    monkeypatch.setattr(service_module, "run_script", fake_run_script)
    target = make_converted_target(
        converter="c",
        converters=[ScriptEntry(id="c", run=["python3", "scripts/c.py"], cache=False)],
    )
    service = _service(tmp_path, {})
    document = make_document()
    # 実行
    first = service.convert(target, document)
    second = service.convert(target, document)
    # 検証
    assert first.markdown.startswith("# 変換した")
    assert second.markdown.startswith("# 変換した")
    assert len(calls) == 2
    assert list((tmp_path / "converted").glob("**/*.*")) == []


def test_convert_service_convert_when_project_index_updated(
    tmp_path: Path,
    make_converted_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """project-index のバージョンが変わったら変換し直す（正常系）。"""
    # 準備
    calls: list[list[str]] = []

    def fake_run_script(run: Any, **kwargs: Any) -> ScriptResult:
        calls.append(list(run))
        return ScriptResult(stdout="# 変換した\n", stderr="")

    monkeypatch.setattr(service_module, "run_script", fake_run_script)
    target = make_converted_target(
        converter="c", converters=[ScriptEntry(id="c", run=["python3", "scripts/c.py"])]
    )
    service = _service(tmp_path, {})
    document = make_document()
    # 実行
    monkeypatch.setattr(service_module, "RUNNING_VERSION", "0.1.0", raising=False)
    service.convert(target, document)
    monkeypatch.setattr(service_module, "RUNNING_VERSION", "0.2.0", raising=False)
    service.convert(target, document)
    # 検証
    assert len(calls) == 2


def test_convert_service_convert_when_timeout(
    tmp_path: Path,
    make_converted_target: Callable[..., Target],
    make_document: Callable[..., Document],
) -> None:
    """制限時間を超える（異常系）。"""
    # 準備
    run = [sys.executable, "-c", "import time; time.sleep(5)"]
    target = make_converted_target(converter="c", converters=[ScriptEntry(id="c", run=run)])
    # 実行
    result = _service(tmp_path, {}, timeout_sec=1).convert(target, make_document())
    # 検証
    assert result.failure is not None
    assert result.failure.reason == "timeout"
    assert result.failure.script == " ".join(run)
    assert "1" in result.failure.detail


def test_convert_service_convert_when_default_ref(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    commit_all: Callable[..., str],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    make_document: Callable[..., Document],
) -> None:
    """`default_ref` のスクリプトで変換する（正常系）。"""
    # 準備
    root = git_repo({"scripts/c.py": 'print("# develop")\n'})
    develop = run_git(root, "rev-parse", "HEAD").strip()
    run_git(root, "checkout", "-b", "master")
    commit_all(root, {"scripts/c.py": 'print("# master")\n'})
    table = DocumentTable(
        id="rules", paths=["rules/*.yaml"], schema_path="schemas/rule.schema.yaml", converter="c"
    )
    config = make_source_config(
        documents=[table],
        converters=[ScriptEntry(id="c", run=[sys.executable, "scripts/c.py"])],
    )
    source = make_served_source(
        root=root,
        config=config,
        is_git=True,
        repo_root=root,
        main_root=root,
        config_commit=develop,
    )
    target = make_target(source, ref=develop, access="read")
    # 実行
    result = _service(tmp_path, {}).convert(target, make_document())
    # 検証
    assert result.failure is None
    assert result.markdown.strip() == "# develop"


# 本文の `body` と、`x-heading: 処理の流れ` の `flow` を持つスキーマ
LINK_SCHEMA = {
    "properties": {
        "name": {"type": "string"},
        "body": {"type": "string", "title": "本文"},
        "flow": {"type": "string", "x-heading": "処理の流れ"},
    }
}

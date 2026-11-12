from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from project_index.shared.yaml_io import load_yaml as load_yaml_value

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest


def load_yaml(text: str) -> Any:
    """形の分かっている YAML の文字列を読む。"""
    return load_yaml_value(text)


SEEN_MARK = "（この会話で返却済み）"
OUTSIDE_LINE = "作業範囲の外（参考）"
OUTSIDE_LOG = "作業範囲の外を読んだ"
CODE_ROW = (
    "  - id: code\n"
    "    paths: [src/files.yaml]\n"
    "    schema: schemas/code.schema.yaml\n"
    "    records: files\n"
    "    body_file: path\n"
)
CODE_SCHEMA = (
    "type: object\n"
    "properties:\n"
    "  files:\n"
    "    type: array\n"
    "    items:\n"
    "      type: object\n"
    "      properties:\n"
    "        path: {type: string}\n"
    "        related:\n"
    "          type: array\n"
    "          items:\n"
    "            type: object\n"
    "            properties:\n"
    "              to: {type: string}\n"
    "              type: {type: string}\n"
)


def _link(target: str) -> list[dict[str, str]]:
    """`references` で target を指す related の値を作る。"""
    return [{"to": target, "type": "references"}]


def _chain_files(
    sample_file_set: Callable[..., dict[str, str]], sample_doc_text: Callable[..., str]
) -> dict[str, str]:
    """文書 1 → 文書 2 → 文書 3 と related が続く配信元のファイル一式を返す。"""
    return sample_file_set(
        **{
            "docs/doc-1.yaml": sample_doc_text("doc-1", "文書 1", related=_link("doc-2")),
            "docs/doc-2.yaml": sample_doc_text("doc-2", "文書 2", related=_link("doc-3")),
            "docs/doc-3.yaml": sample_doc_text("doc-3", "文書 3", description="3 件目"),
        }
    )


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """起点の文書の related をたどって関連する文書を返す（正常系）。"""
    # 準備
    source = make_source("sample", _chain_files(sample_file_set, sample_doc_text))
    env = make_server(source)
    arguments = {"cwd": str(source.folder), "from_ids": ["doc-1"], "direction": "out"}
    # 実行
    deep = env.call("trace_related", format="json", **arguments)
    shallow = env.call("trace_related", format="json", depth=1, **arguments)
    # 検証
    items = deep.data["items"]
    assert [(item["id"], item["depth"]) for item in items] == [("doc-2", 1), ("doc-3", 2)]
    assert items[0]["via"]["from"] == "doc-1"
    assert items[0]["via"]["type"] == "references"
    assert items[1]["via"]["from"] == "doc-2"
    assert [item["id"] for item in shallow.data["items"]] == ["doc-2"]
    assert [(item["path"], item["scope"]) for item in items] == [
        (f"{source.folder}/docs/doc-2.yaml", "summary"),
        (f"{source.folder}/docs/doc-3.yaml", "summary"),
    ]


def test_normal_when_direction_in(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """direction: in で起点を指す文書を返し、循環をたどらない（正常系）。"""
    # 準備
    files = _chain_files(sample_file_set, sample_doc_text)
    files["docs/doc-3.yaml"] = sample_doc_text("doc-3", "文書 3", related=_link("doc-1"))
    source = make_source("sample", files)
    env = make_server(source)
    arguments = {"cwd": str(source.folder), "from_ids": ["doc-3"], "direction": "in"}
    # 実行
    result = env.call("trace_related", format="json", depth=4, **arguments)
    rounded = env.call("trace_related", format="json", depth=5, **arguments)
    # 検証
    assert [(item["id"], item["depth"]) for item in result.data["items"]] == [
        ("doc-2", 1),
        ("doc-1", 2),
    ]
    assert any("4" in note for note in rounded.data["notes"])


def test_normal_when_code_paths(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
    sample_config_text: Callable[..., str],
) -> None:
    """コードのパスを本文に持つ文書を起点にたどる（正常系）。"""
    # 準備
    files = _chain_files(sample_file_set, sample_doc_text)
    files.update(
        {
            "project-index.yaml": sample_config_text(CODE_ROW),
            "schemas/code.schema.yaml": CODE_SCHEMA,
            "src/files.yaml": "files:\n  - path: a.py\n    related:\n"
            "      - {to: doc-1, type: references}\n",
            "src/a.py": "print('a')\n",
        }
    )
    source = make_source("sample", files)
    env = make_server(source)
    # 実行
    result = env.call(
        "trace_related",
        cwd=str(source.folder),
        code_paths=["src/a.py"],
        direction="out",
        format="json",
    )
    # 検証
    assert [(item["id"], item["depth"]) for item in result.data["items"]] == [
        ("doc-1", 1),
        ("doc-2", 2),
    ]


def test_normal_when_suggest(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
    commit_all: Callable[..., str],
) -> None:
    """suggest: true で同じ commit の変更と会話での閲覧から候補を返す（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "docs/doc-1.yaml": sample_doc_text("doc-1", "文書 1", related=_link("doc-2")),
            "docs/doc-4.yaml": sample_doc_text("doc-4", "文書 4"),
            "docs/doc-5.yaml": sample_doc_text("doc-5", "文書 5"),
        }
    )
    source = make_source("sample", files)
    commit_all(
        source.folder,
        {
            "docs/doc-1.yaml": sample_doc_text("doc-1", "文書 1 改", related=_link("doc-2")),
            "docs/doc-4.yaml": sample_doc_text("doc-4", "文書 4 改"),
        },
        "docs: 1 と 4 を一緒に変える",
    )
    env = make_server(source)
    arguments = {"cwd": str(source.folder), "session_id": "s1"}
    for doc_id in ("doc-1", "doc-5"):
        env.call(
            "search_docs",
            filter={"field": "id", "op": "eq", "values": [doc_id]},
            view="full",
            **arguments,
        )
    before = (source.folder / "docs" / "doc-1.yaml").read_text(encoding="utf-8")
    # 実行
    result = env.call("trace_related", from_ids=["doc-1"], suggest=True, format="json", **arguments)
    # 検証
    suggestions = {item["id"]: item["signals"] for item in result.data["suggestions"]}
    assert "co_change" in suggestions["doc-4"]
    assert "viewed" in suggestions["doc-5"]
    assert "doc-2" not in suggestions
    assert (source.folder / "docs" / "doc-1.yaml").read_text(encoding="utf-8") == before
    assert load_yaml(before)["related"] == _link("doc-2")


def test_normal_when_seen(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
) -> None:
    """同じ会話で 2 回目は相手の名前・概要文を省く（正常系）。"""
    # 準備
    source = make_source("sample", _chain_files(sample_file_set, sample_doc_text))
    env = make_server(source)
    arguments = {
        "cwd": str(source.folder),
        "from_ids": ["doc-1"],
        "direction": "out",
        "session_id": "s1",
        "format": "json",
    }
    # 実行
    first = env.call("trace_related", **arguments)
    second = env.call("trace_related", **arguments)
    repeated = env.call("trace_related", repeat_seen=True, **arguments)
    # 検証
    assert [item["name"] for item in first.data["items"]] == ["文書 2", "文書 3"]
    assert [item["name"] for item in second.data["items"]] == [SEEN_MARK, SEEN_MARK]
    assert [item["description"] for item in second.data["items"]] == [SEEN_MARK, SEEN_MARK]
    assert all("path" not in item and "scope" not in item for item in second.data["items"])
    assert [item["name"] for item in repeated.data["items"]] == ["文書 2", "文書 3"]


def test_error_when_document_not_found(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """無い文書・文書の無いコードのパスを起点にすると断る（異常系）。"""
    # 準備
    source = make_source("sample")
    env = make_server(source)
    # 実行
    no_id = env.call("trace_related", cwd=str(source.folder), from_ids=["doc-9"])
    no_path = env.call("trace_related", cwd=str(source.folder), code_paths=["src/none.py"])
    # 検証
    assert no_id.is_error
    assert "DocumentNotFoundError" in no_id.text
    assert "doc-9" in no_id.text
    assert "doc-1" in no_id.text
    assert no_path.is_error
    assert "src/none.py" in no_path.text


def test_error_when_invalid_argument(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """from_ids と code_paths の両方かどちらも無い呼び出しを断る（異常系）。"""
    # 準備
    source = make_source("sample")
    env = make_server(source)
    # 実行
    both = env.call(
        "trace_related", cwd=str(source.folder), from_ids=["doc-1"], code_paths=["src/a.py"]
    )
    neither = env.call("trace_related", cwd=str(source.folder))
    # 検証
    for result in (both, neither):
        assert result.is_error
        assert "InvalidArgumentError" in result.text
        assert "from_ids" in result.text
        assert "code_paths" in result.text


def test_error_when_source_not_readable(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """scope に当たらない配信元を起点にしない（異常系）。"""
    # 準備
    sample = make_source("sample")
    other = make_source("other")
    env = make_server(sample, other)
    # 実行
    result = env.call("trace_related", cwd=str(sample.folder), source="other", from_ids=["doc-1"])
    # 検証
    assert result.is_error
    assert "SourceNotReadableError" in result.text
    assert "other" in result.text
    assert "sample" in result.text


def test_normal_when_outside_scope(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_doc_text: Callable[..., str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """outside_scope: true で、scope に当たらない配信元の関連を作業範囲の外としてたどる（正常系）。"""
    # 準備
    sample = make_source("sample")
    other = make_source("other", _chain_files(sample_file_set, sample_doc_text))
    closed = make_source(
        "closed", _chain_files(sample_file_set, sample_doc_text), outside_read=False
    )
    env = make_server(sample, other, closed)
    cwd = str(sample.folder)
    arguments = {"cwd": cwd, "from_ids": ["doc-1"], "depth": 1, "outside_scope": True}
    caplog.set_level(logging.INFO)
    # 実行
    result = env.call("trace_related", source="other", **arguments)
    as_json = env.call("trace_related", source="other", format="json", **arguments)
    refused = env.call("trace_related", source="closed", **arguments)
    # 検証
    logs = [record.getMessage() for record in caplog.records if OUTSIDE_LOG in record.getMessage()]
    assert not result.is_error
    assert result.text.splitlines()[0] == OUTSIDE_LINE
    assert [item["id"] for item in as_json.data["items"]] == ["doc-2"]
    assert any(cwd in message and "other" in message for message in logs)
    assert refused.is_error
    assert "SourceNotReadableError" in refused.text

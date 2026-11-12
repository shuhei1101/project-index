"""ツールの結果とエラーの変換。"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import ValidationError
from ruamel.yaml import YAML

from project_index.features.changes.types import ChangesResult, ContainsChange
from project_index.features.related.types import RelatedItem
from project_index.features.search.types import SearchItem, SnippetLine
from project_index.features.write.types import DeleteResult
from project_index.shared.narrowing import is_dict, is_list

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from _typeshed import DataclassInstance

    from project_index.shared.errors import ProjectIndexError

TOOL_ANNOTATIONS = {
    "search_docs": ToolAnnotations(read_only_hint=True),
    "describe": ToolAnnotations(read_only_hint=True),
    "list_changes": ToolAnnotations(read_only_hint=True),
    "trace_related": ToolAnnotations(read_only_hint=True),
    "write_docs": ToolAnnotations(read_only_hint=False, destructive_hint=False),
    "delete_docs": ToolAnnotations(read_only_hint=False, destructive_hint=True),
    "list_match_words": ToolAnnotations(read_only_hint=True),
    "status": ToolAnnotations(read_only_hint=True),
    "reload": ToolAnnotations(read_only_hint=False, destructive_hint=False),
    "restart": ToolAnnotations(read_only_hint=False, destructive_hint=True),
    "update": ToolAnnotations(read_only_hint=False, destructive_hint=True),
    "check_project": ToolAnnotations(read_only_hint=True),
    "try_convert": ToolAnnotations(read_only_hint=True),
    "write_nav": ToolAnnotations(read_only_hint=False, destructive_hint=False),
}

# 文書の MCP が登録するツールの名前（登録の順）
DOCS_TOOL_NAMES = (
    "search_docs",
    "describe",
    "list_changes",
    "trace_related",
    "write_docs",
    "delete_docs",
    "list_match_words",
)
# 管理の MCP が登録するツールの名前（登録の順）
ADMIN_TOOL_NAMES = (
    "status",
    "reload",
    "restart",
    "update",
    "check_project",
    "try_convert",
    "write_nav",
)
# 文書の MCP の instructions を描画するプロンプトの ID
DOCS_INSTRUCTIONS_PROMPT_ID = "mcp/docs/instructions"


def tool_prompt_id(server: str, tool: str) -> str:
    """ツールの description を描画するプロンプトの ID を作る（プロンプトの ID はハイフンだけを許す）。"""
    return f"mcp/{server}/tools/{tool.replace('_', '-')}"


def mcp_prompt_ids() -> list[str]:
    """2 つの MCP が描画するプロンプトの ID を並べる。"""
    return [
        DOCS_INSTRUCTIONS_PROMPT_ID,
        *(tool_prompt_id("docs", name) for name in DOCS_TOOL_NAMES),
        *(tool_prompt_id("admin", name) for name in ADMIN_TOOL_NAMES),
    ]


DESCRIBE_HINT = "describe で使用方法（使用できる配信元・種類・スキーマ）を確認してください"


def _fields(value: DataclassInstance) -> dict[str, Any]:
    """dataclass のフィールドを、JSON に出さない内部のフィールドを除いて辞書にする。"""
    return {
        item.name: getattr(value, item.name)
        for item in dataclasses.fields(value)
        if not item.metadata.get("internal")
    }


def _changes(value: ChangesResult) -> object:
    """区間の端を `range` の下にまとめる。"""
    data = _fields(value)
    data["range"] = {"from": data.pop("range_from"), "to": data.pop("range_to")}
    return _plain(data)


def _related(value: RelatedItem) -> object:
    """たどった関連を `via` の下にまとめる。"""
    data = _fields(value)
    data["via"] = {
        "from": data.pop("via_from"),
        "type": data.pop("via_type"),
        "direction": data.pop("via_direction"),
    }
    return _plain(data)


def _deleted(value: DeleteResult) -> object:
    """参照を外した文書を `id`・`version` の辞書の並びにする。"""
    data = _fields(value)
    data["unlinked"] = [{"id": doc_id, "version": version} for doc_id, version in value.unlinked]
    return _plain(data)


def _contains(value: ContainsChange) -> object:
    """区間の始点のキーを `from` にする。"""
    data = _fields(value)
    data["from"] = data.pop("from_")
    return _plain(data)


def _search_item(value: SearchItem) -> object:
    """検索の結果の 1 件。返す行が無くても、切り出したことが分かるよう `ranges: []` を出す。"""
    data = _plain(_fields(value))
    if value.ranges is not None and is_dict(data):
        data["ranges"] = [_plain(item) for item in value.ranges]
    return data


def _snippet_line(value: SnippetLine) -> object:
    """空の行も `line`・`text`・`hit` を全て出す。"""
    return {"line": value.line, "text": value.text, "hit": value.hit}


# 形を変えて出す結果の型と、その変換
_SHAPES: tuple[tuple[type[Any], Callable[[Any], object]], ...] = (
    (ChangesResult, _changes),
    (RelatedItem, _related),
    (DeleteResult, _deleted),
    (ContainsChange, _contains),
    (SearchItem, _search_item),
    (SnippetLine, _snippet_line),
)


def _plain(value: object) -> object:
    """結果を JSON にできる辞書・配列・文字列にする（`None` と空の値は落とす）。"""
    for kind, shape in _SHAPES:
        if isinstance(value, kind):
            return shape(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _plain(_fields(value))
    if is_dict(value):
        return _plain_dict(value)
    if is_list(value) or isinstance(value, tuple):
        # isinstance で絞った tuple は要素の型が Unknown になるため、object の並びとして読む
        items = cast("Iterable[object]", value)
        return [_plain(item) for item in items]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _plain_dict(value: dict[object, object]) -> dict[str, object]:
    """辞書の値を再帰で直し、`None` と空の値（`""`・`[]`・`{}`）のキーを落とす。"""
    cleaned = {str(key): _plain(item) for key, item in value.items() if item is not None}
    return {key: item for key, item in cleaned.items() if item not in ("", [], {})}


def to_tool_result[T](
    result: T,
    fmt: Literal["markdown", "json"],
    render: Callable[[T], str] | None,
) -> CallToolResult:
    """サービスの結果を `format` に合わせて MCP の `CallToolResult` にする。"""
    if fmt == "markdown" and render is not None:
        return CallToolResult(content=[TextContent(type="text", text=render(result))])
    data = _plain(result)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=data)


def _yaml(value: object) -> str:
    """辞書を YAML の文字列にする。"""
    yaml = YAML(typ="safe", pure=True)
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    stream = StringIO()
    yaml.dump(value, stream)
    return stream.getvalue().rstrip("\n")


def tool_error(error: ProjectIndexError | ValidationError) -> CallToolResult:
    """`ProjectIndexError` と要求のモデルの検証の誤りを `isError: true` の結果にする。"""
    if isinstance(error, ValidationError):
        lines = ["InvalidArgumentError: 引数が正しくありません"]
        lines.extend(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()
        )
        lines.append(f"- {DESCRIBE_HINT}")
    else:
        lines = [f"{error.name}: {error.message}"]
        details = _plain(error.details())
        if details:
            lines.append(_yaml(details))
        lines.extend(f"- {step}" for step in error.next_steps)
    return CallToolResult(content=[TextContent(type="text", text="\n".join(lines))], is_error=True)

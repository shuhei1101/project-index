from __future__ import annotations

import json
from typing import TYPE_CHECKING

from project_index.features.outline import service as service_module
from project_index.features.outline.service import (
    judge_next_stage,
    outline_file,
    outline_files,
    to_json_line,
)
from project_index.features.outline.types import (
    CodeOutline,
    ExistingDescription,
    FileOutline,
    MarkdownOutline,
    NextStageReason,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

GUIDE_MD = "# ガイド\n\n使い方の説明です。\n\n## 入れ方\n\n入れる手順です。\n\n## 使い方\n\n使う手順です。\n"


def _markdown_outline(
    *, headings: int, code_block_ratio: float, japanese_ratio: float
) -> MarkdownOutline:
    """判定に使う Markdown のアウトラインを作る。"""
    return MarkdownOutline(
        existing_description=None,
        headings=tuple(f"## h{i}" for i in range(headings)),
        code_block_ratio=code_block_ratio,
        code_languages=(),
        link_count=0,
        image_count=0,
        japanese_ratio=japanese_ratio,
    )


def test_outline_files(tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]) -> None:
    """載せるファイルだけを昇順で返す（正常系）。"""
    # 準備
    write_files(tmp_path, {"docs/b.md": GUIDE_MD, "docs/a.md": GUIDE_MD})
    (tmp_path / "logo.png").write_bytes(b"\x00PNG\r\n")
    # 実行
    result = outline_files(tmp_path, ["**"])
    # 検証
    assert [item.path for item in result] == ["docs/a.md", "docs/b.md"]


def test_outline_file_when_markdown(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """Markdown（正常系）。"""
    # 準備
    write_files(tmp_path, {"a.md": GUIDE_MD})
    # 実行
    result = outline_file(tmp_path, "a.md")
    # 検証
    assert len(result.headings) == 3
    assert result.size == len(GUIDE_MD.encode("utf-8"))
    assert result.next_stage is False


def test_outline_file_when_python(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """Python（正常系）。"""
    # 準備
    write_files(tmp_path, {"a.py": "def f():\n    return 1\n"})
    # 実行
    result = outline_file(tmp_path, "a.py")
    # 検証
    assert result.functions == ("f",)
    assert result.headings == ()
    assert result.next_stage is False


def test_outline_file_when_package_json(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """package.json（正常系）。"""
    # 準備
    write_files(tmp_path, {"package.json": '{"name": "lint", "description": "文書の検査"}'})
    # 実行
    result = outline_file(tmp_path, "package.json")
    # 検証
    assert result.existing_description is not None
    assert result.existing_description.source == "package_json"
    assert result.next_stage is False


def test_outline_file_when_unsupported(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """未対応の形式（正常系）。"""
    # 準備
    write_files(tmp_path, {"a.toml": "a = 1\n"})
    # 実行
    result = outline_file(tmp_path, "a.toml")
    # 検証
    assert result.reasons == (NextStageReason.UNSUPPORTED_FORMAT,)


def test_outline_file_when_large(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """読み取りの上限を超える（正常系）。"""
    # 準備
    monkeypatch.setattr(service_module, "MAX_READ_BYTES", 10)
    content = "abcdefghij\n# 後ろの見出し\n"
    write_files(tmp_path, {"a.md": content})
    # 実行
    result = outline_file(tmp_path, "a.md")
    # 検証
    assert result.size == len(content.encode("utf-8"))
    assert result.headings == ()


def test_judge_next_stage_when_markdown() -> None:
    """Markdown の 3 つのしきい値（正常系）。"""
    # 準備
    outline = _markdown_outline(headings=1, code_block_ratio=0.5, japanese_ratio=0.09)
    # 実行
    result = judge_next_stage(outline)
    # 検証
    assert result == (
        NextStageReason.FEW_HEADINGS,
        NextStageReason.MOSTLY_CODE,
        NextStageReason.NOT_JAPANESE,
    )


def test_judge_next_stage_when_markdown_enough() -> None:
    """しきい値の境目で進まない（正常系）。"""
    # 準備
    outline = _markdown_outline(headings=2, code_block_ratio=0.49, japanese_ratio=0.1)
    # 実行
    result = judge_next_stage(outline)
    # 検証
    assert result == ()


def test_judge_next_stage_when_code_without_definitions() -> None:
    """定義も説明も無いコード（正常系）。"""
    # 準備
    outline = CodeOutline(existing_description=None, functions=(), classes=(), imports=("os",))
    # 実行
    result = judge_next_stage(outline)
    # 検証
    assert result == (NextStageReason.NO_DEFINITIONS,)


def test_judge_next_stage_when_code_with_description() -> None:
    """説明だけを持つコード（正常系）。"""
    # 準備
    outline = CodeOutline(
        existing_description=ExistingDescription(
            source="docstring", title="設定。", description=None
        ),
        functions=(),
        classes=(),
        imports=(),
    )
    # 実行
    result = judge_next_stage(outline)
    # 検証
    assert result == ()


def test_judge_next_stage_when_unsupported() -> None:
    """未対応の形式（正常系）。"""
    # 実行
    result = judge_next_stage(None)
    # 検証
    assert result == (NextStageReason.UNSUPPORTED_FORMAT,)


def test_to_json_line() -> None:
    """インターフェース定義の形（正常系）。"""
    # 準備
    outline = FileOutline(
        path="docs/ログ.md",
        size=120,
        existing_description=None,
        headings=("# 実行ログ",),
        code_block_ratio=0.8234,
        code_languages=("text",),
        link_count=0,
        image_count=0,
        japanese_ratio=0.4,
        functions=(),
        classes=(),
        imports=(),
        next_stage=True,
        reasons=(NextStageReason.MOSTLY_CODE,),
    )
    # 実行
    line = to_json_line(outline)
    # 検証
    assert "\n" not in line
    assert "ログ" in line
    data = json.loads(line)
    assert data["existing_description"] is None
    assert data["reasons"] == ["mostly_code"]
    assert data["code_block_ratio"] == 0.82

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from project_index.features.links.service import (
    build_path_pattern,
    collect_yaml_strings,
    extract_links,
    file_links,
    find_paths,
    links_files,
    resolve_relative,
    to_json_line,
)
from project_index.features.links.types import FileLinks, LinkTarget, LinkVia

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_links_files(tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]) -> None:
    """指す先を持つ Markdown と YAML だけを昇順で返す（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "docs/a.md": "[B](./b.md)\n",
            "docs/b.md": "# b\n",
            "design/x.yaml": "description: src/x.py\n",
            "src/x.py": '"""docs/a.md を参照する。"""\n',
        },
    )
    # 実行
    result = links_files(tmp_path, ["**/*"])
    # 検証
    assert [item.path for item in result] == ["design/x.yaml", "docs/a.md"]


def test_file_links_when_markdown(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """リンクとパスを両方取り出す（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "docs/guide.md": (
                "[API](./api.md) と [外](https://example.com) と [自分](#見出し)\n"
                "`src/a.py` と 詳細はdocs/api.mdを参照\n"
            ),
            "docs/api.md": "# api\n",
            "src/a.py": "a = 1\n",
        },
    )
    existing = frozenset({"docs/guide.md", "docs/api.md", "src/a.py"})
    pattern = build_path_pattern(existing)
    # 実行
    result = file_links(tmp_path, "docs/guide.md", existing, pattern)
    # 検証
    assert result == FileLinks(
        path="docs/guide.md",
        targets=(
            LinkTarget(path="docs/api.md", via=LinkVia.LINK),
            LinkTarget(path="src/a.py", via=LinkVia.PATH),
        ),
    )


def test_file_links_when_yaml(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """YAML の文字列の値から取り出す（正常系）。"""
    # 準備
    write_files(
        tmp_path,
        {
            "design/x.yaml": "description: 実装はsrc/a.pyにある\nnote: src/none.py\n",
            "src/a.py": "a = 1\n",
        },
    )
    existing = frozenset({"design/x.yaml", "src/a.py"})
    pattern = build_path_pattern(existing)
    # 実行
    result = file_links(tmp_path, "design/x.yaml", existing, pattern)
    # 検証
    assert result.targets == (LinkTarget(path="src/a.py", via=LinkVia.PATH),)


def test_file_links_when_self(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """自分自身を指すパスは除く（正常系）。"""
    # 準備
    write_files(tmp_path, {"docs/a.md": "docs/a.md と [自分](./a.md)\n"})
    existing = frozenset({"docs/a.md"})
    pattern = build_path_pattern(existing)
    # 実行
    result = file_links(tmp_path, "docs/a.md", existing, pattern)
    # 検証
    assert result.targets == ()


def test_collect_yaml_strings() -> None:
    """入れ子の文字列の値を集める（正常系）。"""
    # 準備
    text = "a: x\nb:\n  - y\n  - c: z\nd: 1\n"
    # 実行
    result = collect_yaml_strings(text)
    # 検証
    assert result == ["x", "y", "z"]


def test_collect_yaml_strings_when_invalid() -> None:
    """読めない YAML（正常系）。"""
    # 準備
    text = "a: ["
    # 実行
    result = collect_yaml_strings(text)
    # 検証
    assert result == ["a: ["]


def test_extract_links() -> None:
    """リンクと画像の先を取り出す（正常系）。"""
    # 準備
    text = '[A](./a.md) と ![図](img/x.png "t") と src/b.py'
    # 実行
    targets, rest = extract_links(text)
    # 検証
    assert targets == ["./a.md", "img/x.png"]
    assert "src/b.py" in rest
    assert "./a.md" not in rest


def test_find_paths_when_japanese() -> None:
    """空白を挟まない日本語の文の中のパス（正常系）。"""
    # 準備
    existing = frozenset({"docs/guide/設定.md"})
    pattern = build_path_pattern(existing)
    # 実行
    result = find_paths("設定はdocs/guide/設定.mdを参照する", "", existing, pattern)
    # 検証
    assert result == {"docs/guide/設定.md"}


def test_find_paths_when_longest() -> None:
    """同じ位置では最も長い一致を取る（正常系）。"""
    # 準備
    existing = frozenset({"src/a.py", "src/a.py.bak"})
    pattern = build_path_pattern(existing)
    # 実行
    result = find_paths("退避は src/a.py.bak にある", "", existing, pattern)
    # 検証
    assert result == {"src/a.py.bak"}


def test_find_paths_when_boundary() -> None:
    """英数字に続く一致は取らない（正常系）。"""
    # 準備
    existing = frozenset({"src/a.py"})
    pattern = build_path_pattern(existing)
    # 実行
    result = find_paths("xsrc/a.py と src/a.pyc", "", existing, pattern)
    # 検証
    assert result == set()


def test_find_paths_when_relative() -> None:
    """相対パスは指す側のフォルダから解く（正常系）。"""
    # 準備
    existing = frozenset({"docs/api.md", "docs/guide/a.md"})
    pattern = build_path_pattern(existing)
    # 実行
    result = find_paths("../api.mdを参照", "docs/guide", existing, pattern)
    # 検証
    assert result == {"docs/api.md"}


def test_resolve_relative() -> None:
    """後ろに続く文字を削って解く（正常系）。"""
    # 準備
    existing = frozenset({"docs/api.md"})
    # 実行
    result = resolve_relative("./api.mdを参照", "docs", existing)
    # 検証
    assert result == "docs/api.md"


def test_resolve_relative_when_outside_root() -> None:
    """root の外を指す（正常系）。"""
    # 準備
    existing = frozenset({"x.md"})
    # 実行
    result = resolve_relative("../../x.md", "docs", existing)
    # 検証
    assert result is None


def test_build_path_pattern() -> None:
    """接頭辞を共有するパスを両方取る（正常系）。"""
    # 準備
    pattern = build_path_pattern(["docs/a.md", "docs/api.md", "src/a.py"])
    assert pattern is not None
    # 実行
    result = [match.group(1) for match in pattern.finditer("docs/a.md と docs/api.md と src/a.py")]
    # 検証
    assert result == ["docs/a.md", "docs/api.md", "src/a.py"]


def test_build_path_pattern_when_prefix_of_another() -> None:
    """別のパスの接頭辞になるパスは長い方を取る（正常系）。"""
    # 準備
    pattern = build_path_pattern(["src/a.py", "src/a.py.bak"])
    assert pattern is not None
    # 実行
    result = [match.group(1) for match in pattern.finditer("src/a.py.bak と src/a.pyを")]
    # 検証
    assert result == ["src/a.py.bak", "src/a.py"]


def test_build_path_pattern_when_empty() -> None:
    """パスが 0 件（正常系）。"""
    # 準備
    paths: list[str] = []
    # 実行
    result = build_path_pattern(paths)
    # 検証
    assert result is None


def test_to_json_line() -> None:
    """インターフェース定義の形（正常系）。"""
    # 準備
    links = FileLinks(
        path="docs/設定.md", targets=(LinkTarget(path="docs/api.md", via=LinkVia.LINK),)
    )
    # 実行
    line = to_json_line(links)
    # 検証
    assert json.loads(line) == {
        "path": "docs/設定.md",
        "targets": [{"path": "docs/api.md", "via": "link"}],
    }
    assert "設定" in line

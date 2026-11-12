from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

NOTE_CONFIG = (
    "name: sample\n"
    "documents:\n"
    "  - id: note\n"
    "    paths: [docs/*.yaml]\n"
    "    schema: schemas/sample.schema.yaml\n"
    "    converter: note_md\n"
    "converters:\n"
    "  - id: note_md\n"
    "    run: [python3, scripts/convert_note.py]\n"
)
CONVERT_NOTE = "import sys\nsys.stdin.read()\nprint('# 変換したノート')\n"
FAILING_CONVERT = "import sys\nprint('変換に失敗した', file=sys.stderr)\nsys.exit(1)\n"


def _listing(folder: Path) -> dict[str, str]:
    """フォルダの下のファイルのパスと中身を集める。"""
    return {
        str(path.relative_to(folder)): path.read_text(encoding="utf-8")
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def _note_files(
    sample_file_set: Callable[..., dict[str, str]], script: str = CONVERT_NOTE
) -> dict[str, str]:
    """文書の種類 note と、その変換スクリプトを持つ配信元のファイル一式を返す。"""
    return sample_file_set(
        **{
            "project-index.yaml": NOTE_CONFIG,
            "scripts/convert_note.py": script,
            "README.md": "# 読み物\n",
        }
    )


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """変換スクリプトで変換した Markdown を返す（正常系）。"""
    # 準備
    sample = make_source("sample", _note_files(sample_file_set), git=False)
    env = make_server(sample)
    before = _listing(sample.folder)
    # 実行
    result = env.call_admin("try_convert", path=str(sample.folder), file="docs/doc-1.yaml")
    # 検証
    converted = env.state_dir / "converted"
    assert not result.is_error
    assert result.data["kind"] == "note"
    assert result.data["converter"] == "scripts/convert_note.py"
    assert result.data["markdown"].strip() == "# 変換したノート"
    assert _listing(sample.folder) == before
    assert not converted.exists() or list(converted.iterdir()) == []


def test_error_when_document_not_found(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """どの文書の種類にも当たらないファイルを指すと断る（異常系）。"""
    # 準備
    sample = make_source("sample", _note_files(sample_file_set), git=False)
    env = make_server(sample)
    # 実行
    result = env.call_admin("try_convert", path=str(sample.folder), file="README.md")
    # 検証
    assert result.is_error
    assert result.text.startswith("DocumentNotFoundError")


def test_error_when_converter_not_defined(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """converters[] を指さない種類の文書を指すと断る（異常系）。"""
    # 準備
    sample = make_source("sample", sample_file_set(), git=False)
    env = make_server(sample)
    before = _listing(sample.folder)
    # 実行
    result = env.call_admin("try_convert", path=str(sample.folder), file="docs/doc-1.yaml")
    # 検証
    assert result.is_error
    assert result.text.startswith("ConverterNotDefinedError")
    assert "sample" in result.text
    assert "converters" in result.text
    assert _listing(sample.folder) == before


def test_error_when_convert_script_fails(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """変換スクリプトが 0 以外で終わると、終了コードと標準エラーを返す（異常系）。"""
    # 準備
    files = _note_files(sample_file_set, FAILING_CONVERT)
    sample = make_source("sample", files, git=False)
    env = make_server(sample)
    # 実行
    result = env.call_admin("try_convert", path=str(sample.folder), file="docs/doc-1.yaml")
    # 検証
    assert result.is_error
    assert result.text.startswith("ConvertScriptError")
    assert "1" in result.text
    assert "変換に失敗した" in result.text


def test_error_when_config_not_found(tmp_path: Path, make_server: Callable[..., Any]) -> None:
    """project-index.yaml の無いフォルダを指すと断る（異常系）。"""
    # 準備
    env = make_server()
    folder = tmp_path / "empty"
    folder.mkdir()
    # 実行
    result = env.call_admin("try_convert", path=str(folder), file="a.md")
    # 検証
    assert result.is_error
    assert result.text.startswith("ConfigNotFoundError")


def test_error_when_invalid_config(tmp_path: Path, make_server: Callable[..., Any]) -> None:
    """違反のある設定では変換せず断る（異常系）。"""
    # 準備
    env = make_server()
    folder = tmp_path / "draft"
    folder.mkdir()
    (folder / "a.md").write_text("# a\n", encoding="utf-8")
    before = _listing(folder)
    config = "documents:\n  - id: notes\n    type: markdown\n    paths: [a.md]\n"
    # 実行
    result = env.call_admin("try_convert", path=str(folder), file="a.md", config=config)
    # 検証
    assert result.is_error
    assert result.text.startswith("ValidationFailedError")
    assert "1" in result.text
    assert "check_project" in result.text
    assert _listing(folder) == before


def test_error_when_config_parse_error(tmp_path: Path, make_server: Callable[..., Any]) -> None:
    """YAML として読めない設定では断る（異常系）。"""
    # 準備
    env = make_server()
    (tmp_path / "a.md").write_text("# a\n", encoding="utf-8")
    # 実行
    result = env.call_admin("try_convert", path=str(tmp_path), file="a.md", config="name: [")
    # 検証
    assert result.is_error
    assert result.text.startswith("ConfigParseError")

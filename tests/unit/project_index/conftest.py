from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from project_index.features.access.types import Target
from project_index.features.documents.types import Document
from project_index.features.settings.query import load_terminal_config
from project_index.features.settings.types import SourceEntry, SourceScope, TerminalConfig
from project_index.features.sources.registry import SourceRegistry
from project_index.features.sources.types import (
    DocumentTable,
    ScriptEntry,
    ServedSource,
    SourceConfig,
    SourceStatus,
)
from project_index.main import Handlers, build_handlers
from project_index.shared.errors import UnknownSourceError
from project_index.shared.yaml_io import dump_roundtrip, load_roundtrip

if TYPE_CHECKING:
    from collections.abc import Callable

SAMPLE_SCHEMA = (
    "title: rule\n"
    "type: object\n"
    "properties:\n"
    "  id: {type: string}\n"
    "  name: {type: string}\n"
    "required: [id, name]\n"
)

SAMPLE_CONFIG = (
    "name: sample\n"
    "documents:\n"
    "  - id: rules\n"
    "    paths: [docs/rule/*.yaml]\n"
    "    schema: schemas/rule.schema.yaml\n"
)


@pytest.fixture
def sample_files() -> dict[str, str]:
    """検証を通る最小の配信元のファイル一式（設定・スキーマ・文書 2 件）を返す。"""
    return {
        "project-index.yaml": SAMPLE_CONFIG,
        "schemas/rule.schema.yaml": SAMPLE_SCHEMA,
        "docs/rule/doc-1.yaml": "id: doc-1\nname: 文書 1\n",
        "docs/rule/doc-2.yaml": "id: doc-2\nname: 文書 2\n",
    }


@pytest.fixture
def make_terminal_config(tmp_path: Path) -> Callable[..., TerminalConfig]:
    """端末の設定を作る関数を返す。"""

    def _make(**overrides: Any) -> TerminalConfig:
        state_dir = overrides.pop("state_dir", tmp_path / "state")
        values: dict[str, Any] = {
            "file": tmp_path / "settings.yaml",
            "version": "1",
            "clone": tmp_path / "clone",
            "state_dir": state_dir,
            "log_dir": state_dir / "logs",
        }
        values.update(overrides)
        return TerminalConfig(**values)

    return _make


@pytest.fixture
def make_entry() -> Callable[..., SourceEntry]:
    """端末の設定の `sources[]` の行を作る関数を返す。"""

    def _make(
        config: str | list[str], *, source_id: str | None = None, **overrides: Any
    ) -> SourceEntry:
        paths = [config] if isinstance(config, str) else config
        scope = overrides.pop("scope", SourceScope())
        return SourceEntry(id=source_id, config=paths, scope=scope, **overrides)

    return _make


@pytest.fixture
def make_source_config() -> Callable[..., SourceConfig]:
    """配信元の設定を作る関数を返す。"""

    def _make(**overrides: Any) -> SourceConfig:
        values: dict[str, Any] = {
            "name": "sample",
            "documents": [
                DocumentTable(
                    id="rules",
                    paths=["docs/rule/*.yaml"],
                    schema_path="schemas/rule.schema.yaml",
                )
            ],
        }
        values.update(overrides)
        return SourceConfig(**values)

    return _make


@pytest.fixture
def make_served_source(
    tmp_path: Path, make_source_config: Callable[..., SourceConfig]
) -> Callable[..., ServedSource]:
    """配信中の配信元を作る関数を返す。"""

    def _make(**overrides: Any) -> ServedSource:
        root = overrides.pop("root", tmp_path / "sample")
        values: dict[str, Any] = {
            "id": "sample",
            "root": root,
            "config_files": [root / "project-index.yaml"],
            "config": make_source_config(),
            "is_git": False,
            "repo_root": None,
            "scope_read": [],
            "scope_write": [str(root)],
            "worktree_globs": [],
            "schemas": {},
        }
        values.update(overrides)
        return ServedSource(**values)

    return _make


@pytest.fixture
def make_status() -> Callable[..., SourceStatus]:
    """配信元の状態を作る関数を返す。"""

    def _make(
        source_id: str, index: int, status: str = "serving", **overrides: Any
    ) -> SourceStatus:
        return SourceStatus(id=source_id, index=index, status=status, **overrides)  # type: ignore[arg-type]

    return _make


@pytest.fixture
def make_script() -> Callable[..., ScriptEntry]:
    """スクリプトの行を作る関数を返す。"""

    def _make(script_id: str, *run: str) -> ScriptEntry:
        return ScriptEntry(id=script_id, run=list(run))

    return _make


@pytest.fixture
def make_handlers(make_terminal_config: Callable[..., TerminalConfig]) -> Callable[..., Any]:
    """指定した部品だけ偽物にした配線済みの関数を作る関数を返す。"""
    import dataclasses
    import threading

    from project_index.main import Handlers

    def _make(**overrides: Any) -> Handlers:
        values: dict[str, Any] = {field.name: None for field in dataclasses.fields(Handlers)}
        values.update(
            {
                "terminal": make_terminal_config(),
                "settings_lock": threading.Lock(),
                "reload_sources": lambda terminal: [],
            }
        )
        values.update(overrides)
        return Handlers(**values)

    return _make


@pytest.fixture
def bundled_prompts() -> Any:
    """同梱したプロンプトの YAML を、サーバーが描画する全ての ID で読んだ一式を返す。"""
    from project_index.features.prompt_doc.runtime import DEFAULT_PROMPTS_DIR, load_prompts
    from project_index.server.mcp.result import mcp_prompt_ids

    return load_prompts(DEFAULT_PROMPTS_DIR, required=mcp_prompt_ids())


@pytest.fixture
def make_mcp_handlers(
    make_handlers: Callable[..., Any], bundled_prompts: Any
) -> Callable[..., Any]:
    """同梱したプロンプトの一式を持たせ、指定した部品だけ偽物にした配線済みの関数を作る関数を返す。"""

    def _make(**overrides: Any) -> Any:
        return make_handlers(
            **{"prompts": bundled_prompts, "registry": SourceRegistry(), **overrides}
        )

    return _make


class FakeRegistry(SourceRegistry):
    """決めた配信元を返す配信元の一覧の偽物。"""

    def __init__(self, sources: list[ServedSource]) -> None:
        super().__init__()
        self._sources = sources

    def served(self) -> list[ServedSource]:
        return list(self._sources)

    def get(self, source_id: str) -> ServedSource:
        matches = [source for source in self._sources if source.id == source_id]
        if not matches:
            raise UnknownSourceError(
                message=f"配信元 {source_id} はありません", source_id=source_id
            )
        return matches[0]

    def statuses(self) -> list[SourceStatus]:
        return [
            SourceStatus(id=source.id, index=index, status="serving")
            for index, source in enumerate(self._sources)
        ]


@pytest.fixture
def make_registry() -> Callable[..., FakeRegistry]:
    """配信元の一覧の偽物を作る関数を返す。"""

    def _make(*sources: ServedSource) -> FakeRegistry:
        return FakeRegistry(list(sources))

    return _make


@pytest.fixture
def make_target() -> Callable[..., Target]:
    """読み書きの場所を作る関数を返す。"""

    def _make(source: ServedSource, **overrides: Any) -> Target:
        values: dict[str, Any] = {
            "source": source,
            "base": source.root,
            "ref": None,
            "worktree": None,
            "access": "write",
        }
        values.update(overrides)
        return Target(**values)

    return _make


@pytest.fixture
def make_document() -> Callable[..., Document]:
    """文書を作る関数を返す。"""

    def _make(**overrides: Any) -> Document:
        values: dict[str, Any] = {
            "id": "doc-1",
            "kind": "rules",
            "source_id": "sample",
            "path": "rules/doc-1.yaml",
            "record_index": None,
            "data": {"id": "doc-1", "name": "文書 1"},
            "body": "id: doc-1\nname: 文書 1\n",
            "body_path": None,
            "metadata": {"id": "doc-1", "name": "文書 1"},
            "version": "9d0e11",
            "created": None,
            "updated": None,
        }
        values.update(overrides)
        return Document(**values)

    return _make


FILES_SCHEMA = (
    "title: file\n"
    "type: object\n"
    "properties:\n"
    "  files:\n"
    "    type: array\n"
    "    items:\n"
    "      type: object\n"
)

SOURCE_CONFIG_TEMPLATE = (
    "name: {name}\n"
    "{version}"
    "documents:\n"
    "  - id: rules\n"
    "    paths: [docs/rule/*.yaml]\n"
    "    schema: schemas/rule.schema.yaml\n"
)

FILES_ROW = (
    "  - id: src\n"
    "    paths: [src/files.yaml]\n"
    "    schema: schemas/files.schema.yaml\n"
    "    records: files\n"
    "    body_file: path\n"
)


@pytest.fixture
def make_source_dir(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> Callable[..., Path]:
    """検証を通る配信元のフォルダを作り、`project-index.yaml` のパスを返す関数を返す。

    `unindexed` は管理用の YAML に無いファイルの数、`version` は設定の `version`。
    """

    def _make(name: str, *, unindexed: int = 0, version: str | None = None) -> Path:
        root = tmp_path / name
        version_line = "" if version is None else f'version: "{version}"\n'
        config = SOURCE_CONFIG_TEMPLATE.format(name=name, version=version_line)
        files = {
            "schemas/rule.schema.yaml": SAMPLE_SCHEMA,
            "docs/rule/doc-1.yaml": "id: doc-1\nname: 文書 1\n",
        }
        if unindexed:
            config += FILES_ROW
            files["schemas/files.schema.yaml"] = FILES_SCHEMA
            files["src/files.yaml"] = "files:\n  - path: a.py\n"
            files["src/a.py"] = "a = 1\n"
            files.update({f"src/u{index}.py": "x = 1\n" for index in range(unindexed)})
        files["project-index.yaml"] = config
        write_files(root, files)
        return root / "project-index.yaml"

    return _make


@pytest.fixture
def write_settings(tmp_path: Path) -> Callable[..., Path]:
    """端末の設定をファイルに書き、そのパスを返す関数を返す（JSON は YAML として読める）。"""

    def _write(sources: list[dict[str, Any]], **top: Any) -> Path:
        values: dict[str, Any] = {
            "version": "1",
            "clone": str(tmp_path / "clone"),
            "state_dir": str(tmp_path / "state"),
            "sources": sources,
        }
        values.update(top)
        path = tmp_path / "settings.yaml"
        path.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def make_real_handlers() -> Callable[[Path], Handlers]:
    """端末の設定のファイルを読み、部品を本物で配線した配線済みの関数を作る関数を返す。"""

    def _make(settings: Path) -> Handlers:
        terminal = load_terminal_config(settings)
        handlers = build_handlers(terminal)
        handlers.reload_sources(terminal)
        return handlers

    return _make


@pytest.fixture
def migrations_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """移し替えの手順の置き場所を一時のフォルダに差し替え、そのフォルダを返す。

    絶対パスを手順のフォルダの名前に差し替えると、パッケージのフォルダにつないでも絶対パスが残る。
    """
    root = tmp_path / "migrations"
    root.mkdir()
    monkeypatch.setattr("project_index.features.migrate.types.MIGRATIONS_DIR", str(root))
    monkeypatch.setattr(
        "project_index.features.migrate.steps.MIGRATIONS_DIR", str(root), raising=False
    )
    return root


@pytest.fixture
def write_steps(migrations_root: Path) -> Callable[..., None]:
    """移し替えの手順のファイル（`{kind}/{バージョン}/steps.yaml`）を書く関数を返す。"""

    def _write(kind: str, version: str, steps: list[dict[str, Any]]) -> None:
        target = migrations_root / kind / version / "steps.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"steps": steps}, ensure_ascii=False), encoding="utf-8")

    return _write


@pytest.fixture
def settings_version_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """project-index が読める端末の設定のバージョンを `2` に差し替える。"""
    monkeypatch.setattr("project_index.features.settings.query.SETTINGS_VERSION", "2")
    for target in (
        "project_index.features.migrate.service.SETTINGS_VERSION",
        "project_index.features.admin.service.SETTINGS_VERSION",
        "project_index.main.SETTINGS_VERSION",
    ):
        monkeypatch.setattr(target, "2", raising=False)


ALIAS_CONFIG = (
    "name: {name}\n"
    "documents:\n"
    "  - id: rules\n"
    "    paths: [docs/rule/*.yaml]\n"
    "    schema: schemas/rule.schema.yaml\n"
    "  - id: terms\n"
    "    paths: [docs/term/*.yaml]\n"
    "    schema: schemas/term.schema.yaml\n"
    "    alias_type: term\n"
    "  - id: refs\n"
    "    paths: [docs/ref/*.yaml]\n"
    "    schema: schemas/term.schema.yaml\n"
    "    alias_type: doc\n"
)

TERM_SCHEMA = "title: term\ntype: object\n"

# どの文書にも当たらない `auto` の条件のタブ `none` を持つ nav
NONE_NAV = (
    "nav:\n"
    "  tabs:\n"
    "    - title: 規約\n"
    "      items:\n"
    "        - auto: {document: rules}\n"
    "    - title: none\n"
    "      items:\n"
    "        - auto: {filter: {field: tags, op: eq, values: [none]}}\n"
)


@pytest.fixture
def make_alias_source_dir(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> Callable[..., Path]:
    """`alias_type` の行を持つ配信元のフォルダを作り、`project-index.yaml` のパスを返す関数を返す。

    用語「作業範囲」と文書の別名「設定のリファレンス」を置く。`broken` は `aliases` が `3` の用語「壊れた用語」を置くか、`none_nav` はどの文書にも当たらない条件のタブ `none` を持つ `nav` を置くか。
    """

    def _make(name: str = "sample", *, broken: bool = False, none_nav: bool = False) -> Path:
        root = tmp_path / name
        files = {
            "project-index.yaml": ALIAS_CONFIG.format(name=name) + (NONE_NAV if none_nav else ""),
            "schemas/rule.schema.yaml": SAMPLE_SCHEMA,
            "schemas/term.schema.yaml": TERM_SCHEMA,
            "docs/rule/doc-1.yaml": "id: doc-1\nname: 文書 1\n",
            "docs/term/scope.yaml": (
                "id: scope\n"
                "name: 作業範囲\n"
                "description: 触ってよい範囲\n"
                "aliases: [scope, 担当範囲]\n"
                "avoid: [担当領域]\n"
            ),
            "docs/ref/settings.yaml": (
                "id: settings\n"
                "name: 設定のリファレンス\n"
                "description: 設定のキーの一覧\n"
                "aliases: [settings]\n"
            ),
        }
        if broken:
            files["docs/term/broken.yaml"] = (
                "id: broken\nname: 壊れた用語\ndescription: 型の違う別名\naliases: 3\n"
            )
        write_files(root, files)
        return root / "project-index.yaml"

    return _make


REPO_ROOT = Path(__file__).parents[3]

RECORDS_NAV_CONFIG = (
    "name: sample\n"
    "documents:\n"
    "  - id: notes\n"
    "    paths: [notes/files.yaml]\n"
    "    schema: schemas/files.schema.yaml\n"
    "    records: files\n"
    "    body_file: path\n"
)


def records_files_schema(field: str, field_type: str) -> str:
    """`templates/files.schema.yaml` の 1 行の項目に `field`（型 `field_type`）を追加したスキーマを返す。"""
    schema = load_roundtrip(
        (REPO_ROOT / "templates" / "files.schema.yaml").read_text(encoding="utf-8")
    )
    schema["properties"]["files"]["items"]["properties"][field] = {"type": field_type}
    return dump_roundtrip(schema)


@pytest.fixture
def make_records_nav_source_dir(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> Callable[..., Path]:
    """1 行に項目を追加した `records: files` の行 `notes` の配信元のフォルダを作り、`project-index.yaml` のパスを返す関数を返す。

    `values` はファイル名（拡張子 `.md`）→ 項目 `field` の値、`nav_filter` はあれば行 `notes` をその条件で絞るタブ `notes` を持つ `nav` を置く。
    """

    def _make(
        field: str,
        field_type: str,
        values: dict[str, Any],
        *,
        nav_filter: dict[str, Any] | None = None,
    ) -> Path:
        root = tmp_path / "sample"
        rows = "".join(
            f"  - path: {stem}.md\n    {field}: {value}\n" for stem, value in values.items()
        )
        config = RECORDS_NAV_CONFIG
        if nav_filter is not None:
            auto = json.dumps({"document": "notes", "filter": nav_filter})
            config += f"nav:\n  tabs:\n    - title: notes\n      items:\n        - auto: {auto}\n"
        files = {
            "project-index.yaml": config,
            "schemas/files.schema.yaml": records_files_schema(field, field_type),
            "notes/files.yaml": "files:\n" + rows,
            **{f"notes/{stem}.md": f"# {stem}\n" for stem in values},
        }
        write_files(root, files)
        return root / "project-index.yaml"

    return _make

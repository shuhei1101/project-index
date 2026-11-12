"""端末の設定の読み込み。"""

from __future__ import annotations

import os
from importlib import resources
from typing import TYPE_CHECKING

from project_index.features.settings.types import (
    SourceEntry,
    TerminalConfig,
    TerminalConfigInvalidError,
)
from project_index.shared.errors import Violation
from project_index.shared.narrowing import is_dict, is_list
from project_index.shared.paths import normalize_path
from project_index.shared.schema_check import schema_violations
from project_index.shared.yaml_io import YamlLoadError, load_yaml

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

DEFAULT_CONFIG_HOME = "~/.config"
CONFIG_FILE = "project-index/settings.yaml"
DEFAULT_STATE_HOME = "~/.local/state"
STATE_SUBDIR = "project-index"
XDG_CONFIG_HOME_ENV = "XDG_CONFIG_HOME"
XDG_STATE_HOME_ENV = "XDG_STATE_HOME"
CONFIG_ENV = "PROJECT_INDEX_CONFIG"
PORT_ENV = "PROJECT_INDEX_PORT"
STATE_DIR_ENV = "PROJECT_INDEX_STATE_DIR"
SETTINGS_SCHEMA = "schemas/settings.schema.yaml"
SETTINGS_VERSION = "1"
PORT_MIN = 1
PORT_MAX = 65535


def xdg_base_dir(env: Mapping[str, str], name: str, default: str) -> Path:
    """XDG の環境変数の値を、空の文字列か相対パスなら既定に替えて返す。"""
    value = env.get(name) or ""
    # XDG Base Directory Specification は相対パスを無効として無視する
    return normalize_path(value if os.path.isabs(value) else default)


def config_path(env: Mapping[str, str]) -> Path:
    """環境変数から端末の設定のパスを決める。"""
    value = env.get(CONFIG_ENV)
    if value:
        return normalize_path(value)
    return xdg_base_dir(env, XDG_CONFIG_HOME_ENV, DEFAULT_CONFIG_HOME) / CONFIG_FILE


def state_dir_path(value: str | None, env: Mapping[str, str]) -> Path:
    """環境変数と端末の設定の `state_dir` から状態の置き場を決める。"""
    override = env.get(STATE_DIR_ENV)
    if override:
        return normalize_path(override)
    if value:
        return normalize_path(value)
    return xdg_base_dir(env, XDG_STATE_HOME_ENV, DEFAULT_STATE_HOME) / STATE_SUBDIR


def _settings_schema() -> object:
    """配布に同梱した端末の設定のスキーマを読む。"""
    text = resources.files("project_index").joinpath(SETTINGS_SCHEMA).read_text(encoding="utf-8")
    return load_yaml(text)


def validate_terminal_config(value: object) -> list[Violation]:
    """端末の設定の値をスキーマと行の間の決まりで確かめ、違反を全て返す。"""
    violations = schema_violations(_settings_schema(), value)
    if not is_dict(value):
        return violations
    sources = value.get("sources")
    if is_list(sources):
        violations.extend(_duplicate_ids(sources))
        violations.extend(_empty_globs(sources))
    # 読めるバージョンより新しい設定
    version = value.get("version")
    if isinstance(version, str) and version.isdigit() and int(version) > int(SETTINGS_VERSION):
        violations.append(Violation(path="version", rule="このサーバーより新しい設定です"))
    return violations


def _duplicate_ids(sources: list[object]) -> list[Violation]:
    """行の ID が先の行と重なる違反を集める（id を省いた行は配信元の読み込みで比べる）。"""
    violations: list[Violation] = []
    seen: set[str] = set()
    for index, row in enumerate(sources):
        row_id = row.get("id") if is_dict(row) else None
        if not isinstance(row_id, str):
            continue
        if row_id in seen:
            violations.append(
                Violation(
                    path=f"sources[{index}].id",
                    rule=f"{row_id} は既に使用されています",
                    fix="別の ID にしてください",
                )
            )
        seen.add(row_id)
    return violations


def _empty_globs(sources: list[object]) -> list[Violation]:
    """作業場所の glob にある空の文字列の違反を集める。"""
    violations: list[Violation] = []
    for index, row in enumerate(sources):
        scope = row.get("scope") if is_dict(row) else None
        if not is_dict(scope):
            continue
        for key in ("read", "write"):
            globs = scope.get(key)
            if not is_list(globs):
                continue
            violations.extend(
                Violation(
                    path=f"sources[{index}].scope.{key}[{position}]",
                    rule="空の文字列は記載できません",
                )
                for position, glob in enumerate(globs)
                if glob == ""
            )
    return violations


def load_terminal_config(path: Path, *, env: Mapping[str, str] | None = None) -> TerminalConfig:
    """`settings.yaml` を読み、スキーマの違反を全て集めてから端末の設定にする。"""
    if not path.is_file():
        raise TerminalConfigInvalidError(file=path, message=f"{path}: 端末の設定が見つかりません")
    try:
        value = load_yaml(path.read_text(encoding="utf-8"), file=str(path))
    except YamlLoadError as error:
        location = f"{error.line}:{error.column}: " if error.line else ""
        raise TerminalConfigInvalidError(
            file=path,
            message=str(error),
            violations=[Violation(path="$", rule=f"{location}{error.reason}")],
        ) from error
    violations = validate_terminal_config(value if value is not None else {})
    if violations:
        raise TerminalConfigInvalidError(
            file=path,
            message=f"{path}: 端末の設定に違反が {len(violations)} 件あります",
            violations=violations,
        )
    # スキーマを通った設定は辞書（空のファイルは空の辞書として扱う）
    data: dict[object, object] = value if is_dict(value) else {}
    state_value = data.get("state_dir")
    state_dir = state_dir_path(
        state_value if isinstance(state_value, str) else None, os.environ if env is None else env
    )
    log_value = data.get("log_dir")
    log_dir = normalize_path(str(log_value)) if "log_dir" in data else state_dir / "logs"
    values = {
        key: data[key]
        for key in ("port", "bind", "seen_retention_days", "script_timeout_sec")
        if key in data
    }
    return TerminalConfig.model_validate(
        {
            "file": path,
            "version": data["version"],
            "clone": normalize_path(str(data["clone"])),
            "state_dir": state_dir,
            "log_dir": log_dir,
            "sources": [SourceEntry.model_validate(row) for row in _rows(data.get("sources"))],
            **values,
        }
    )


def _rows(value: object) -> list[object]:
    """`sources` の値を行の並びにする（無ければ空）。"""
    return value if is_list(value) else []


def listen_port(config: TerminalConfig, env: Mapping[str, str]) -> int:
    """`PROJECT_INDEX_PORT` を優先して待ち受けのポートを決める。"""
    raw = env.get(PORT_ENV)
    if not raw:
        return config.port
    if raw.isdecimal() and PORT_MIN <= int(raw) <= PORT_MAX:
        return int(raw)
    raise TerminalConfigInvalidError(
        file=config.file,
        message=f"{PORT_ENV}: 1〜65535 の整数にしてください（{raw}）",
    )

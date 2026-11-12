"""端末の設定の読み込み。"""
# pyright: reportUnknownArgumentType=warning, reportUnknownMemberType=warning, reportUnknownVariableType=warning

from __future__ import annotations

import logging
import os
from importlib import resources
from typing import TYPE_CHECKING, Any

from project_index.features.settings.types import (
    SettingsWarning,
    SourceEntry,
    TerminalConfig,
    TerminalConfigInvalidError,
)
from project_index.shared.errors import Violation
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
UNKNOWN_KEY_REASON = "project-index が知らないキーです。値は使用せず、ファイルに残します"
PORT_MIN = 1
PORT_MAX = 65535

logger = logging.getLogger(__name__)


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


def _settings_schema() -> dict[str, Any]:
    """配布に同梱した端末の設定のスキーマを読む。"""
    text = resources.files("project_index").joinpath(SETTINGS_SCHEMA).read_text(encoding="utf-8")
    schema: dict[str, Any] = load_yaml(text)
    return schema


def validate_terminal_config(value: Any) -> list[Violation]:  # noqa: ANN401, C901
    """端末の設定の値をスキーマと行の間の決まりで確かめ、違反を全て返す。"""
    violations = schema_violations(_settings_schema(), value)
    if not isinstance(value, dict):
        return violations
    sources = value.get("sources")
    if isinstance(sources, list):
        seen: set[str] = set()
        for index, row in enumerate(sources):
            if not isinstance(row, dict):
                continue
            # 行の ID が先の行と重なる（id を省いた行は配信元の読み込みで比べる）
            row_id = row.get("id")
            if isinstance(row_id, str):
                if row_id in seen:
                    violations.append(
                        Violation(
                            path=f"sources[{index}].id",
                            rule=f"{row_id} は既に使用されています",
                            fix="別の ID にしてください",
                        )
                    )
                seen.add(row_id)
            # 作業場所の glob に空の文字列がある
            scope = row.get("scope")
            if isinstance(scope, dict):
                for key in ("read", "write"):
                    globs = scope.get(key)
                    if not isinstance(globs, list):
                        continue
                    for position, glob in enumerate(globs):
                        if glob == "":
                            violations.append(
                                Violation(
                                    path=f"sources[{index}].scope.{key}[{position}]",
                                    rule="空の文字列は記載できません",
                                )
                            )
    # 読めるバージョンより新しい設定
    version = value.get("version")
    if isinstance(version, str) and version.isdigit() and int(version) > int(SETTINGS_VERSION):
        violations.append(Violation(path="version", rule="このサーバーより新しい設定です"))
    return violations


def unknown_top_level_keys(value: dict[str, Any]) -> list[str]:
    """端末の設定の値の最上位の、スキーマの `properties` に無いキーをファイルの順に返す。"""
    known = set(_settings_schema()["properties"])
    return [key for key in value if key not in known]


def unknown_key_warnings(config: TerminalConfig) -> list[SettingsWarning]:
    """端末の設定の知らないキーを、端末の設定の API の警告の並びにする。"""
    return [SettingsWarning(path=key, reason=UNKNOWN_KEY_REASON) for key in config.unknown_keys]


def log_unknown_keys(config: TerminalConfig) -> None:
    """端末の設定の知らないキーを警告のログに書く。"""
    if config.unknown_keys:
        logger.warning(
            "端末の設定に project-index が知らないキーがある（%s・%s）",
            config.file,
            ", ".join(config.unknown_keys),
        )


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
    value = value or {}
    state_dir = state_dir_path(value.get("state_dir"), os.environ if env is None else env)
    log_dir = normalize_path(value["log_dir"]) if "log_dir" in value else state_dir / "logs"
    values: dict[str, Any] = {
        key: value[key]
        for key in ("port", "bind", "seen_retention_days", "script_timeout_sec")
        if key in value
    }
    return TerminalConfig(
        file=path,
        unknown_keys=unknown_top_level_keys(value),
        version=value["version"],
        clone=normalize_path(value["clone"]),
        state_dir=state_dir,
        log_dir=log_dir,
        sources=[SourceEntry.model_validate(row) for row in value.get("sources", [])],
        **values,
    )


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

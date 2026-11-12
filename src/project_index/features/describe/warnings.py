"""引数なしの `describe` に添える警告。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.admin.service import version_state
from project_index.features.settings.query import SETTINGS_VERSION
from project_index.features.sources.types import SOURCE_CONFIG_VERSION

if TYPE_CHECKING:
    from project_index.features.access.types import SourceAccess
    from project_index.features.describe.source_checks import SourceChecks
    from project_index.features.settings.types import TerminalConfig
    from project_index.features.sources.registry import SourceRegistry

TERMINAL_LABEL = "端末の設定"


def collect_warnings(
    available: list[SourceAccess],
    *,
    registry: SourceRegistry,
    checks: SourceChecks,
    terminal: TerminalConfig,
) -> list[str]:
    """使える配信元の同期のずれ・古い設定と、端末の設定の古さ・配信していない配信元を警告の文にする。"""
    warnings: list[str] = []
    old_sources: list[str] = []
    config_warnings: list[str] = []
    for item in available:
        source = registry.get(item.source_id)
        if version_state(source.config.version, SOURCE_CONFIG_VERSION) == "old":
            old_sources.append(
                _old_version(item.source_id, source.config.version, SOURCE_CONFIG_VERSION)
            )
        # 配信元のファイルはたどらず、最後の検査の結果を読む
        check = checks.get(item.source_id)
        if check is None:
            continue
        report = check.report
        for label, values in (
            ("metadata の列の欠け", report.missing_refs),
            ("管理用の YAML に無いファイル", report.unindexed_files),
            ("ファイルが無い行", report.missing_body_files),
            ("どの文書にも該当しない関連", report.unresolved_related),
        ):
            if values:
                warnings.append(
                    f"{item.source_id}: {label}が {len(values)} 件あります"
                    "（check_project で確認できます）"
                )
        if report.alias_violations:
            config_warnings.append(
                f"{item.source_id}: エイリアスのキーの違反が {len(report.alias_violations)} 件"
                "あります（check_project で確認できます）"
            )
        config_warnings.extend(
            f"{item.source_id}: {warning.path}: {warning.rule}" for warning in check.nav
        )
    warnings.extend(old_sources)
    # 端末の設定のバージョンが古い（使える配信元が無くても載せる）
    if version_state(terminal.version, SETTINGS_VERSION) == "old":
        warnings.append(_old_version(TERMINAL_LABEL, terminal.version, SETTINGS_VERSION))
    warnings.extend(config_warnings)
    # 検証で外した配信元（使える配信元かによらない）
    for status in registry.statuses():
        if status.status == "not_served" and status.errors:
            first = status.errors[0]
            warnings.append(
                f"{status.id}: 配信していません（{first.path}: {first.rule}）。"
                "check_project で確認できます"
            )
    return warnings


def _old_version(label: str, mine: str, current: str) -> str:
    """設定のバージョンが古いことを知らせる文を作る。"""
    return (
        f"{label}: 設定のバージョンが古い（{mine}・読み込める {current}）。"
        "project-index migrate で移し替えます"
    )

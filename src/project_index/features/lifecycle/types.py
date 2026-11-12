"""再起動と更新の結果の型と定数。"""

from __future__ import annotations

from dataclasses import dataclass

# `git pull`・`uv sync`・`migrate --plan` それぞれの打ち切りの秒数
COMMAND_TIMEOUT_SEC = 300
# 処理中の要求を待つ上限を `script_timeout_sec` の何倍にするか
SHUTDOWN_WAIT_FACTOR = 1.5
# `os.execv` に渡す `sys.executable` の後ろの引数
SERVE_ARGV = ("-m", "project_index", "serve")


@dataclass(frozen=True)
class RestartResult:
    """`restart` の結果。"""

    pid: int
    restarting: bool = True


@dataclass(frozen=True)
class UpdateResult:
    """`update` の結果。"""

    previous_version: str
    version: str
    updated: bool
    migration_needed: bool
    restarting: bool

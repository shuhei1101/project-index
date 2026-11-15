"""1 回のツールの呼び出しの期限と取り消しの合図。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from project_index.shared.errors import WriteDeadlineExceededError


@dataclass(frozen=True, slots=True, kw_only=True)
class Deadline:
    """要求を受けた時刻から決めた秒数の後の時刻と、そこまでの残りの時間。"""

    limit_sec: float
    started: float
    # 壁時計ではなく単調な時計の秒で比べる
    clock: Callable[[], float] = time.monotonic

    def remaining(self) -> float:
        """期限までの残りの秒数を返す（過ぎていれば 0）。"""
        return max(0.0, self.started + self.limit_sec - self.clock())

    def cap(self, timeout_sec: float) -> float:
        """スクリプトの制限時間を、期限までの残りの時間との短い方にする。"""
        return min(timeout_sec, self.remaining())

    def check(self) -> None:
        """期限を過ぎていれば書き込みの期限の超過を送る。"""
        if self.remaining() > 0:
            return
        elapsed = round(self.clock() - self.started, 1)
        raise WriteDeadlineExceededError(
            message=(
                f"書き込みの期限（{self.limit_sec:g} 秒）を超えたため、"
                f"ファイルを書き換えずに止めました（経過 {elapsed:g} 秒）"
            ),
            deadline_sec=self.limit_sec,
            elapsed_sec=elapsed,
            next_steps=["検査のスクリプトの所要時間を確認してから再実行してください"],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CallLimits:
    """1 回のツールの呼び出しの書き込みの期限・応答の上限・取り消しの合図。"""

    write_deadline: Deadline
    respond_by: Deadline
    # MCP の取り消しの通知を受けたら文書の MCP が立てる
    cancelled: threading.Event = field(default_factory=threading.Event)

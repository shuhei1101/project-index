"""SessionStart のフック。落ちている project-index を起動し、`/clear`・圧縮のときは返し済みの記録の削除を依頼する。

Usage:
# Claude Code が stdin に SessionStart の入力の JSON を渡して実行する
python3 session_start.py
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_PORT = 8786
# `XDG_CONFIG_HOME` が無いか空の文字列か相対パスのときの設定の置き場の親
DEFAULT_CONFIG_HOME = "~/.config"
CONFIG_FILE = "project-index/settings.yaml"
# ポートへの TCP 接続を打ち切る秒数
CONNECT_TIMEOUT_SEC = 0.5
# `POST /_admin/session-start` を打ち切る秒数（実装の後に応答の時間を測って決め直す）
FORGET_TIMEOUT_SEC = 3
# 返し済みの記録の削除を依頼する `source`
FORGET_REASONS = frozenset({"clear", "compact"})
# 起動したときに文脈に入れる文
RECONNECT_GUIDE = (
    "project-index を起動しました。"
    "このセッションで文書の MCP を使用するには /mcp で project-index に再接続してください。"
)
CLONE_KEY = "clone:"


def is_listening(port: int) -> bool:
    """`127.0.0.1:{port}` に TCP でつながるかを返す。"""
    try:
        socket.create_connection(("127.0.0.1", port), timeout=CONNECT_TIMEOUT_SEC).close()
    except OSError:
        return False
    return True


def config_path(env: Mapping[str, str]) -> Path:
    """サーバーと同じ規則で端末の設定のパスを決める。"""
    value = env.get("PROJECT_INDEX_CONFIG")
    if value:
        return Path(value).expanduser()
    home = env.get("XDG_CONFIG_HOME") or ""
    base = Path(home) if os.path.isabs(home) else Path(DEFAULT_CONFIG_HOME).expanduser()
    return base / CONFIG_FILE


def read_clone(config: Path) -> Path | None:
    """端末の設定のトップレベルの `clone:` の行だけを読む（標準ライブラリに YAML が無いため）。"""
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        # 行頭が `clone:` の最初の行だけを見る（字下げした行は別のキー）
        if line.startswith(CLONE_KEY):
            value = line[len(CLONE_KEY) :].split("#", 1)[0].strip().strip("\"'")
            return Path(value).expanduser() if value else None
    return None


def start_server(clone: Path) -> None:
    """クローンの `.venv` で `project-index serve` を切り離して起動し、待たずに戻る。"""
    python = clone / ".venv" / "bin" / "python"
    if not python.exists():
        raise FileNotFoundError(str(python))
    subprocess.Popen(  # noqa: S603
        [str(python), "-m", "project_index", "serve"],
        cwd=clone,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def request_forget(port: int, payload: dict[str, str]) -> None:
    """`POST /_admin/session-start` を 1 回呼ぶ。"""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/_admin/session-start",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=FORGET_TIMEOUT_SEC) as response:  # noqa: S310
        body = json.load(response)
    if not isinstance(body, dict):
        msg = "応答を読み込めません"
        raise ValueError(msg)


def _unavailable(reason: str) -> str:
    """起動できないことと、端末の設定の作り方を知らせる文を作る。"""
    return (
        f"project-index を起動できませんでした（{reason}）。"
        "/project-index:global-setup で端末の設定を作ってください。"
    )


def _start_context(clone: Path | None, config: Path) -> str:
    """サーバーを起動し、起動できたときは案内、できなかったときは理由の文を返す。"""
    # 端末の設定か clone の行が無い
    if clone is None:
        return _unavailable(str(config))
    # `{clone}/.venv/bin/python` が無い
    python = clone / ".venv" / "bin" / "python"
    if not python.exists():
        return _unavailable(str(python))
    try:
        start_server(clone)
    except OSError as error:
        return _unavailable(str(error))
    return RECONNECT_GUIDE


def _forget_context(port: int, event: dict[str, Any]) -> str | None:
    """`/clear`・圧縮のときだけ記録の削除を依頼し、失敗したときだけ理由の文を返す。"""
    reason = str(event.get("source", "startup"))
    session_id = event.get("session_id")
    if reason not in FORGET_REASONS or not session_id:
        return None
    payload = {"session_id": str(session_id), "reason": reason}
    if event.get("agent_id"):
        payload["agent_id"] = str(event["agent_id"])
    try:
        request_forget(port, payload)
    except (OSError, ValueError) as error:
        # 打ち切ったとき: 理由の代わりに打ち切った秒数を入れる
        timed_out = isinstance(error, TimeoutError) or (
            isinstance(error, urllib.error.URLError) and isinstance(error.reason, TimeoutError)
        )
        detail = f"{FORGET_TIMEOUT_SEC} 秒で打ち切りました" if timed_out else str(error)
        return (
            f"project-index の返却済みの記録を削除できませんでした（{detail}）。"
            "前に返却した文書は repeat_seen: true で再取得できます。"
        )
    return None


def _context(event: dict[str, Any]) -> str | None:
    """フックの入力から、セッションの文脈に入れる文を決める（入れないときは `None`）。"""
    port = int(os.environ.get("PROJECT_INDEX_PORT") or DEFAULT_PORT)
    # 待ち受けているサーバーには、記録の削除だけを依頼する
    if is_listening(port):
        return _forget_context(port, event)
    # 落ちているサーバーは、端末の設定のクローンで起動する
    config = config_path(os.environ)
    return _start_context(read_clone(config), config)


def main() -> int:
    """stdin の JSON を読み、サーバーを起動するか記録の削除を依頼して、入れる文だけを出す。"""
    try:
        loaded: object = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(loaded, dict):
        return 0
    # JSON の辞書のキーは文字列
    event = cast("dict[str, Any]", loaded)
    try:
        context = _context(event)
    # フックはどの失敗でも終了コード 0 で戻り、セッションを止めない（失敗は文脈に書く）
    except Exception as error:  # noqa: BLE001
        context = f"project-index のフックが失敗しました（{error}）。"
    if context is None:
        return 0
    output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

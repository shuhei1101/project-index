"""端末の設定の project-index の行の config を develop の worktree へ付け替え、dev-docs に読み直させる。"""

import difflib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from http import HTTPStatus
from pathlib import Path

SETTINGS = Path.home() / ".config/dev-docs/settings.yaml"
BACKUP = SETTINGS.with_name("settings.yaml.bak-project-index")
CLONE = Path("/mnt/c/Users/shuhe/repo/project-index")
DEVELOP_WORKTREE = CLONE / ".claude/worktrees/develop"
OLD_LINE = (
    "    config: /mnt/c/Users/shuhe/repo/project-index/.claude/worktrees/"
    "chore-project-index-bootstrap/dev-docs.yaml\n"
)
NEW_LINE = (
    "    config: /mnt/c/Users/shuhe/repo/project-index/.claude/worktrees/develop/dev-docs.yaml\n"
)
ADMIN_MCP = "http://127.0.0.1:8781/_admin/mcp/"
# dev-docs の読み直しは配信元の数だけ時間がかかり、実測で 10 分を超えたため 30 分まで待つ
RELOAD_TIMEOUT_SEC = 1800


def ensure_develop_worktree(dry_run: bool) -> bool:
    """develop の worktree が無ければ作り、develop に dev-docs.yaml があるかを返す。"""
    # develop に配信元の設定が入っているか（作業 PR のマージの後でないと無い）
    shown = subprocess.run(
        ["git", "-C", str(CLONE), "cat-file", "-e", "origin/develop:dev-docs.yaml"],
        check=False,
        capture_output=True,
    )
    if shown.returncode != 0:
        print("develop の dev-docs.yaml: failed")
        return False
    print("develop の dev-docs.yaml: ok")
    # worktree が既にあれば何もしない
    if DEVELOP_WORKTREE.is_dir():
        print("develop の worktree: skipped")
        return True
    if dry_run:
        print("develop の worktree: changed")
        return True
    subprocess.run(
        ["git", "-C", str(CLONE), "worktree", "add", str(DEVELOP_WORKTREE), "develop"],
        check=True,
    )
    print("develop の worktree: changed")
    return True


def call_reload() -> bool:
    """dev-docs の管理の MCP の reload を呼び、応答が返ったかを返す。"""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "reload", "arguments": {}},
        }
    ).encode()
    request = urllib.request.Request(
        ADMIN_MCP,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    with urllib.request.urlopen(request, timeout=RELOAD_TIMEOUT_SEC) as response:  # noqa: S310
        return response.status == HTTPStatus.OK


def main() -> int:
    """前提確認 → 計画 → 適用の順に進め、failed があれば 1 を返す。"""
    dry_run = len(sys.argv) > 1 and sys.argv[1] == "--dry-run"
    # 前提確認
    git_fetch = subprocess.run(
        ["git", "-C", str(CLONE), "fetch", "origin", "develop"], check=False, capture_output=True
    )
    if not SETTINGS.is_file() or git_fetch.returncode != 0:
        print("前提確認: failed")
        return 1
    current = SETTINGS.read_text(encoding="utf-8")
    # 既に develop の worktree を指していれば何もしない
    if NEW_LINE in current and OLD_LINE not in current:
        print("前提確認: ok")
        print("端末の設定の書き換え: skipped")
        return 0
    # 付け替える行がちょうど 1 つあるか
    if current.count(OLD_LINE) != 1:
        print("前提確認: failed")
        return 1
    print("前提確認: ok")
    if not ensure_develop_worktree(dry_run):
        return 1
    # 計画（--dry-run もここを通る）
    updated = current.replace(OLD_LINE, NEW_LINE)
    sys.stdout.writelines(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=str(SETTINGS),
            tofile=str(SETTINGS),
        )
    )
    if dry_run:
        print("端末の設定の書き換え: changed")
        print("dev-docs の読み直し: changed")
        return 0
    # 適用（一時ファイル → 検証 → 退避 → 置き換え）
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=SETTINGS.parent, delete=False
    ) as tmp:
        tmp.write(updated)
    tmp_path = Path(tmp.name)
    if NEW_LINE not in tmp_path.read_text(encoding="utf-8"):
        tmp_path.unlink()
        print("検証: failed")
        return 1
    print("検証: ok")
    shutil.copy2(SETTINGS, BACKUP)
    tmp_path.replace(SETTINGS)
    print("端末の設定の書き換え: changed")
    # 変更があったので 1 回だけ読み直させる
    try:
        reloaded = call_reload()
    except OSError:
        reloaded = False
    print(f"dev-docs の読み直し: {'changed' if reloaded else 'failed'}")
    return 0 if reloaded else 1


if __name__ == "__main__":
    sys.exit(main())

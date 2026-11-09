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


def git(*args: str) -> subprocess.CompletedProcess[str]:
    """project-index のクローンで git を実行する。"""
    return subprocess.run(
        ["git", "-C", str(CLONE), *args], check=False, capture_output=True, text=True
    )


def sync_develop_worktree(dry_run: bool) -> bool:
    """develop の worktree を origin/develop に揃え、そこに dev-docs.yaml があるかを返す。"""
    # origin/develop に配信元の設定が入っているか（作業 PR のマージの後でないと無い）
    if git("cat-file", "-e", "origin/develop:dev-docs.yaml").returncode != 0:
        print("develop の dev-docs.yaml: failed")
        return False
    print("develop の dev-docs.yaml: ok")
    target = git("rev-parse", "origin/develop").stdout.strip()
    # worktree が無い: 手元の develop を origin/develop へ合わせて作る
    if not DEVELOP_WORKTREE.is_dir():
        if not dry_run:
            added = git("worktree", "add", "-B", "develop", str(DEVELOP_WORKTREE), "origin/develop")
            if added.returncode != 0:
                print("develop の worktree: failed")
                return False
        print("develop の worktree: changed")
        return True
    # worktree がある: origin/develop まで早送りする
    head = subprocess.run(
        ["git", "-C", str(DEVELOP_WORKTREE), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head == target:
        print("develop の worktree: skipped")
    else:
        if not dry_run:
            merged = subprocess.run(
                ["git", "-C", str(DEVELOP_WORKTREE), "merge", "--ff-only", "origin/develop"],
                check=False,
                capture_output=True,
            )
            if merged.returncode != 0:
                print("develop の worktree: failed")
                return False
        print("develop の worktree: changed")
    # 付け替え先の設定のファイルがあるか（dry-run で worktree を作っていないときは確かめない）
    if not (DEVELOP_WORKTREE / "dev-docs.yaml").is_file() and not dry_run:
        print("develop の worktree の dev-docs.yaml: failed")
        return False
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


def rewrite_settings(current: str, dry_run: bool) -> bool:
    """端末の設定の参照先を develop の worktree へ書き換え、失敗したら False を返す。"""
    # 既に develop の worktree を指していれば書き換えない
    if NEW_LINE in current and OLD_LINE not in current:
        print("端末の設定の書き換え: skipped")
        return True
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
        return True
    # 適用（一時ファイル → 検証 → 退避 → 置き換え）
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=SETTINGS.parent, delete=False
    ) as tmp:
        tmp.write(updated)
    tmp_path = Path(tmp.name)
    if NEW_LINE not in tmp_path.read_text(encoding="utf-8"):
        tmp_path.unlink()
        print("検証: failed")
        return False
    print("検証: ok")
    shutil.copy2(SETTINGS, BACKUP)
    tmp_path.replace(SETTINGS)
    print("端末の設定の書き換え: changed")
    return True


def main() -> int:
    """前提確認 → 計画 → 適用の順に進め、failed があれば 1 を返す。"""
    dry_run = len(sys.argv) > 1 and sys.argv[1] == "--dry-run"
    # 前提確認: 端末の設定があり、origin/develop を取り込める
    if not SETTINGS.is_file() or git("fetch", "origin", "develop").returncode != 0:
        print("前提確認: failed")
        return 1
    current = SETTINGS.read_text(encoding="utf-8")
    # 付け替える前の行がちょうど 1 つあるか、既に付け替え済みか
    already = NEW_LINE in current and OLD_LINE not in current
    if not already and current.count(OLD_LINE) != 1:
        print("前提確認: failed")
        return 1
    print("前提確認: ok")
    if not sync_develop_worktree(dry_run):
        return 1
    if not rewrite_settings(current, dry_run):
        return 1
    # 読み直しは書き換えの有無によらず行う（前回の読み直しが失敗していても取り戻せる）
    if dry_run:
        print("dev-docs の読み直し: changed")
        return 0
    try:
        reloaded = call_reload()
    except OSError:
        reloaded = False
    print(f"dev-docs の読み直し: {'changed' if reloaded else 'failed'}")
    return 0 if reloaded else 1


if __name__ == "__main__":
    sys.exit(main())

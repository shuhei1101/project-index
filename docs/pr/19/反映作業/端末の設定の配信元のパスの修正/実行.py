"""端末の設定の配信元 project-index の config を develop の worktree の project-index.yaml へ書き換え、dev-docs に読み直させる。"""

import difflib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from http import HTTPStatus
from pathlib import Path

SETTINGS = Path("/home/shuhei2441/.config/dev-docs/settings.yaml")
BACKUP = Path("/home/shuhei2441/.config/dev-docs/settings.yaml.bak-pr19")
CLONE = Path("/mnt/c/Users/shuhe/repo/project-index")
OLD_LINE = (
    "    config: /mnt/c/Users/shuhe/repo/project-index/.claude/worktrees/develop/dev-docs.yaml\n"
)
NEW_LINE = "    config: /mnt/c/Users/shuhe/repo/project-index/.claude/worktrees/develop/project-index.yaml\n"
NEW_CONFIG = Path(
    "/mnt/c/Users/shuhe/repo/project-index/.claude/worktrees/develop/project-index.yaml"
)
ADMIN_MCP = "http://127.0.0.1:8781/_admin/mcp/"
# PR #3 の実測で読み直しが 10 分を超えたため、同じく 30 分まで待つ
RELOAD_TIMEOUT_SEC = 1800


def precheck(argv: list[str]) -> str | None:
    """引数と端末の設定を確かめ、端末の設定の本文を返す。満たさなければ None を返す。"""
    if len(argv) > 1 or (len(argv) == 1 and argv[0] != "--dry-run"):
        print("前提確認: failed")
        print(f"引数: {' '.join(argv)}")
        return None
    if not SETTINGS.is_file():
        print("前提確認: failed")
        print(f"{SETTINGS} が無い")
        return None
    current = SETTINGS.read_text(encoding="utf-8")
    already = NEW_LINE in current and OLD_LINE not in current
    if not already and current.count(OLD_LINE) != 1:
        print("前提確認: failed")
        print(f"書き換える前の行の数: {current.count(OLD_LINE)}")
        return None
    print("前提確認: ok")
    return current


def check_develop(dry_run: bool) -> bool:
    """dev-docs が読む develop のリビジョンと worktree に project-index.yaml があるかを確かめる。"""
    # dev-docs は config をディスクではなく default_ref（develop）のリビジョンから読む
    found = (
        subprocess.run(
            ["git", "-C", str(CLONE), "cat-file", "-e", "develop:project-index.yaml"],
            check=False,
            capture_output=True,
        ).returncode
        == 0
        and NEW_CONFIG.is_file()
    )
    if found:
        print("develop の project-index.yaml: ok")
        return True
    # マージの前の dry-run は、無いことを示して計画まで進める
    print(f"develop の project-index.yaml: {'missing' if dry_run else 'failed'}")
    return dry_run


def rewrite_settings(current: str, dry_run: bool) -> bool:
    """端末の設定の config を書き換え、失敗したら False を返す。"""
    if NEW_LINE in current and OLD_LINE not in current:
        print("配信元 project-index の config の書き換え: skipped")
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
        print("配信元 project-index の config の書き換え: changed")
        return True
    # 適用（一時ファイル → 検証 → 退避 → 置き換え）
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=SETTINGS.parent, delete=False
    ) as tmp:
        tmp.write(updated)
    tmp_path = Path(tmp.name)
    written = tmp_path.read_text(encoding="utf-8")
    if NEW_LINE not in written or OLD_LINE in written:
        tmp_path.unlink()
        print("検証: failed")
        return False
    print("検証: ok")
    shutil.copy2(SETTINGS, BACKUP)
    tmp_path.replace(SETTINGS)
    print("配信元 project-index の config の書き換え: changed")
    return True


def call_reload() -> str:
    """dev-docs の管理の MCP の reload を呼び、返った本文を返す。"""
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
        if response.status != HTTPStatus.OK:
            return ""
        raw = response.read().decode("utf-8")
    # 応答は JSON か、SSE の data: の行に JSON を載せた形で返る
    payload = next(
        (
            line.removeprefix("data:").strip()
            for line in raw.splitlines()
            if line.startswith("data:")
        ),
        raw,
    )
    result = json.loads(payload)["result"]
    return "".join(part.get("text", "") for part in result["content"])


def reload_sources() -> bool:
    """dev-docs に読み直させ、project-index が配信されていれば True を返す。"""
    try:
        text = call_reload()
    except (OSError, ValueError, KeyError) as exc:
        print("dev-docs の読み直し: failed")
        print(f"POST {ADMIN_MCP} reload: {exc}")
        return False
    not_served = next((line for line in text.splitlines() if "配信していない:" in line), "")
    if not text or not not_served or "project-index（" in not_served:
        print("dev-docs の読み直し: failed")
        print(not_served or text)
        return False
    print("dev-docs の読み直し: changed")
    return True


def main() -> int:
    """前提確認 → 計画 → 適用の順に進め、failed があれば 1 を返す。"""
    argv = sys.argv[1:]
    current = precheck(argv)
    if current is None:
        return 1
    dry_run = argv == ["--dry-run"]
    if not check_develop(dry_run):
        return 1
    if not rewrite_settings(current, dry_run):
        return 1
    # 読み直しは書き換えの有無によらず行う（前回の読み直しが失敗していても取り戻せる）
    if dry_run:
        print("dev-docs の読み直し: changed")
        return 0
    return 0 if reload_sources() else 1


if __name__ == "__main__":
    sys.exit(main())

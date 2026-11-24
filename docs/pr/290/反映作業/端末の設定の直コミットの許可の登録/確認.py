"""配信元 project-index の行が、配信元の設定の全ての種類を直コミットできる種類として持つかを観測する。"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402


def main() -> int:
    """観測した値を出し、どれかが合わなければ 1 を返却する。"""
    status, body = common.request("GET", "/settings/sources")
    row = common.api_row(body) if status == 200 else None
    if row is None:
        print("端末の設定の API: failed")
        print(f"GET /settings/sources: {status}（{common.TARGET} の行が無いか応答が 200 でない）", file=sys.stderr)
        return 1
    expected = common.allowed_kinds() or []
    actual = common.write_api_kinds(row)
    failed = False
    ok = bool(expected) and actual == expected
    print(f"{common.TARGET} の writeApiKinds: {'ok' if ok else 'failed'}（{actual}）")
    failed = failed or not ok
    # 配信を続けているか
    served = row.get("status")
    ok = served == "serving"
    print(f"{common.TARGET} の状態: {'ok' if ok else 'failed'}（{served}）")
    failed = failed or not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

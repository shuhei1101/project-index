"""配信元 project-index の行の write_api_kinds を登録の前の空の並びへ戻し、再読み込みさせる。"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402


def main() -> int:
    """1 行の変更で write_api_kinds に空の並びを送信する。"""
    status, body = common.request("GET", "/settings/sources")
    if status != 200 or common.api_row(body) is None:
        print("直コミットできる種類の戻し: failed")
        print(f"GET /settings/sources: {status}（{common.TARGET} の行が無いか応答が 200 でない）", file=sys.stderr)
        return 1
    status, result = common.request(
        "PATCH",
        f"/settings/sources/{common.TARGET}",
        {"expectedVersion": body["version"], "source": {"direct_commit": {"write_api_kinds": []}}},
    )
    if status != 200:
        print("直コミットできる種類の戻し: failed")
        print(f"PATCH /settings/sources/{common.TARGET}: {status} {result}", file=sys.stderr)
        return 1
    print("直コミットできる種類の戻し: changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

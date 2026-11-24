"""配信元の設定のファイルと端末の設定の API に、読み取りだけでつながるかを確認する。"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402


def main() -> int:
    """対象ごとに 1 行の結果を出し、`failed` があれば 1 を返却する。"""
    failed = False
    # 配信元の設定のファイル
    if common.CONFIG.is_file():
        print("配信元の設定のファイル: ok")
    else:
        print("配信元の設定のファイル: failed")
        print(f"{common.CONFIG} がありません", file=sys.stderr)
        failed = True
    # 端末の設定の API と対象の行
    try:
        status, body = common.request("GET", "/settings/sources")
        ok = status == common.HTTP_OK and common.api_row(body) is not None
        print("端末の設定の API: " + ("ok" if ok else "failed"))
        if not ok:
            print(
                f"GET /settings/sources: {status}（{common.TARGET} の行が無いか応答が 200 でない）",
                file=sys.stderr,
            )
        failed = failed or not ok
    except RuntimeError as error:
        print("端末の設定の API: failed")
        print(error, file=sys.stderr)
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""配信元 project-index の行に、書き込みの API から直コミットできる種類を登録する。

1 行の変更（PATCH）で `write_api_kinds` を送信して、その行の配信元を再読み込みさせる。
"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402


def fail(step: str, detail: str) -> int:
    """失敗の行と詳細を出して 1 を返却する。"""
    print(f"{step}: failed")
    print(detail, file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    """前提確認 → 計画 → 適用の順に進める。"""
    # 前提確認: 引数は無しか --dry-run だけ
    if len(argv) > 1 or (len(argv) == 1 and argv[0] != "--dry-run"):
        return fail("前提確認", f"受け付けない引数です: {argv}")
    dry_run = argv == ["--dry-run"]
    if not common.CONFIG.is_file():
        return fail("前提確認", f"{common.CONFIG} がありません")
    kinds = common.allowed_kinds()
    # 配信元の設定に direct_commit が無い: マージした変更が develop のワークツリーへ入っていない
    if not kinds:
        return fail("前提確認", f"{common.CONFIG} に direct_commit.kinds がありません")
    try:
        status, body = common.request("GET", "/settings/sources")
    except RuntimeError as error:
        return fail("前提確認", str(error))
    if status != 200:
        return fail("前提確認", f"GET /settings/sources: {status} {body}")
    row = common.api_row(body)
    if row is None:
        return fail("前提確認", f"端末の設定に {common.TARGET} の行がありません")
    print("前提確認: ok")

    # 計画: 送信する write_api_kinds
    current = common.write_api_kinds(row)
    if current == kinds:
        print("直コミットできる種類の登録: skipped")
        return 0
    print(f"{common.TARGET} の write_api_kinds: {current} → {kinds}")
    if dry_run:
        print("直コミットできる種類の登録: changed")
        return 0

    # 適用: 1 行の変更で write_api_kinds を送信し、その行の配信元を再読み込みさせる
    status, result = common.request(
        "PATCH",
        f"/settings/sources/{common.TARGET}",
        {"expectedVersion": body["version"], "source": {"direct_commit": {"write_api_kinds": kinds}}},
    )
    if status != 200:
        return fail("直コミットできる種類の登録", f"PATCH /settings/sources/{common.TARGET}: {status} {result}")
    print("直コミットできる種類の登録: changed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

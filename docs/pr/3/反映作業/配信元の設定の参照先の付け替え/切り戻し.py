"""実行で退避した端末の設定を書き戻す。"""

import shutil
import sys
from pathlib import Path

SETTINGS = Path.home() / ".config/dev-docs/settings.yaml"
BACKUP = SETTINGS.with_name("settings.yaml.bak-project-index")


def main() -> int:
    """退避したファイルがあれば書き戻し、無ければ 1 を返す。"""
    if not BACKUP.is_file():
        print("退避したファイル: failed")
        return 1
    shutil.copy2(BACKUP, SETTINGS)
    print("端末の設定の書き戻し: changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

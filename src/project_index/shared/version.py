"""動いているプロセスが起動した時点の project-index のバージョン。"""

from __future__ import annotations

from importlib.metadata import version

from project_index import DIST_NAME

# 更新で配布のメタデータが入れ替わっても変わらないよう、読み込んだ時点の値を持つ
RUNNING_VERSION = version(DIST_NAME)

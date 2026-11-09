# project-index

文書とソースコードの索引・検索・書き込みを提供するサービス。

## ドキュメント

実体は [docs/](./docs/) にあり、Schema は [schemas/](./schemas/) にある。
使い方は [guide](./docs/guide/)。

着手前に索引を引いて読む。

```bash
PROJECT_ROOT="$PWD" PYTHONPATH="$AI_MONITOR_HOME/src" python3 -m ai_monitor.inject.build_docs_index
```

# project-index

文書とソースコードの索引・検索・書き込みを提供するサービス。

## 構成

| 場所 | 中身 |
| --- | --- |
| `src/project_index/` | 索引のサーバー（文書の MCP・管理の MCP・読み取り API・端末の設定の API） |
| `plugins/project-index/` | プラグイン（`.mcp.json`・フック・スキル） |
| `templates/` | 配信元の設定・端末の設定の雛形 |
| `content/prompts/` | MCP の instructions とツールの説明のプロンプト |

## ドキュメント

実体は [docs/](./docs/) にあり、Schema は [schemas/](./schemas/) にある。
使い方は [guide](./docs/guide/)。

着手前に索引を引いて読む。

```bash
PROJECT_ROOT="$PWD" PYTHONPATH="$AI_MONITOR_HOME/src" python3 -m ai_monitor.inject.build_docs_index
```

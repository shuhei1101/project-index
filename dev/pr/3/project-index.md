# project-index

## 現状

なし（初回 commit の `README.md` だけで、設計書も実装も無い）

切り出し元の dev-docs の所在。

| 分類 | ページ / ファイル | 概要 | 補足 |
| --- | --- | --- | --- |
| ドキュメント | [dev-docs: dev/設計書/モジュール構成/開発ドキュメントサーバー/分類/](https://github.com/shuhei1101/dev-docs/blob/develop/dev/%E8%A8%AD%E8%A8%88%E6%9B%B8/%E3%83%A2%E3%82%B8%E3%83%A5%E3%83%BC%E3%83%AB%E6%A7%8B%E6%88%90/%E9%96%8B%E7%99%BA%E3%83%89%E3%82%AD%E3%83%A5%E3%83%A1%E3%83%B3%E3%83%88%E3%82%B5%E3%83%BC%E3%83%90%E3%83%BC/%E5%88%86%E9%A1%9E/) | 開発ドキュメントサーバーの分類 | 骨組みのフォルダ構成の参考。中身は shuhei1101/dev-docs#114 で移す |
| 実装 | [dev-docs: src/dev_docs/](https://github.com/shuhei1101/dev-docs/blob/develop/src/dev_docs/) | 開発ドキュメントサーバーの実装 | 同上 |
| 実装 | [dev-docs: plugins/dev-docs/](https://github.com/shuhei1101/dev-docs/blob/develop/plugins/dev-docs/) | フック・スキルのプラグイン | 同上 |
| 設定 | [dev-docs: pyproject.toml](https://github.com/shuhei1101/dev-docs/blob/develop/pyproject.toml) | Python 3.14・uv・hatchling・FastAPI・MCP・ruamel.yaml・jsonschema | 骨組みの依存の参考 |

## 変更方針

| 対象 | 方針 | 補足 |
| --- | --- | --- |
| フォルダ構成 | `src/project_index/`（パッケージ）・`plugins/project-index/`（プラグイン）・`tests/`・`dev/`・`docs/` を置く | 分類ごとの中身は shuhei1101/dev-docs#114 |
| パッケージ | `pyproject.toml` で `project-index` を定義し、`project-index` コマンド（`--version` だけを受ける）を起動の入口にする | 実行時の依存（FastAPI・MCP・ruamel.yaml・jsonschema）は、それを使うコードと一緒に shuhei1101/dev-docs#114 で加える |
| プラグイン | `plugins/project-index/.claude-plugin/plugin.json` と `.claude-plugin/marketplace.json` を置く | MCP の接続・フック・スキルは、接続先のサーバーと一緒に shuhei1101/dev-docs#114 で加える |
| データの保存先 | 端末の設定・状態のフォルダ・配信元の設定の既定のパスを設定の設計書に記載する | 済（設定『索引のサーバー』） |
| 配信元の設定 | 作業中は `dev-docs.yaml` の `default_ref` を作業ブランチにし、マージの前に `develop` へ戻す | 設定は `default_ref` のリビジョンから読まれ、develop にはまだ無いため |
| 既存機能への影響 | なし（dev-docs の動作を変えない） | - |

## 設計書の確定コミット

| 工程 | 範囲 | 補足 |
| --- | --- | --- |
| モジュール構成設計 | `a7dabdf..104753d` | 設定の設計書を含む |

## テスト結果

### 単体

なし

### 結合

なし

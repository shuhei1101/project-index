# 開発ドキュメントのサイドバーで、インターフェース定義とモジュール構成のグループを入れ子にする

## 概要

dev-docs の画面のサイドバーで、利用者がインターフェース定義とモジュール構成を入れ子のグループからたどって探せるようになる。

## 背景

[Issue #302](https://github.com/shuhei1101/project-index/issues/302) の要望。
project-index の `nav` の `group` は子の `items[]` に `group` を持てる（入れ子にできる）ようになったが、この配信元の [project-index.yaml](https://github.com/shuhei1101/project-index/blob/2588d67cf5b95cb1a593cca4cf5189440a502ae1/project-index.yaml) の `nav` はグループが 1 階層だけで、タブ「設計書」に `インターフェース定義 / 文書の MCP`・`モジュール構成 / パッケージ` のようにグループ名の `/` で階層を表したグループが 40 件近く並んでいる。
1 階層のグループは [#111](https://github.com/shuhei1101/project-index/pull/111) で規約『開発ドキュメントのナビゲーション』に沿って定義した。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理と影響する UC・更新ドキュメント・スコープ外 |
| [タスク一覧](./tasks.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.mark.md) | 配信元の設定の `nav` の計画書 |

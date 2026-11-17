# documents[].metadata の列名に、どの深さの同じ名前の列もまとめて取り出す記載を追加する

## 概要

配信元の設定の `documents[].metadata` で、文書の最上位と配列の要素の中にある同じ名前の列を、1 つの共通のキーへまとめて対応づけられるようにする。

## 背景

[Issue #98](https://github.com/shuhei1101/project-index/issues/98) の要望。利用する側は [shuhei1101/ai-monitor#3042](https://github.com/shuhei1101/ai-monitor/issues/3042)。
`documents[].metadata` の列名は `meta.summary`・`tags[].name`・`tags[main].name` の記載で、文書の中の 1 か所の列しか指せない。
AI Monitor の設計書は、最上位の `refs` と `categories[].refs`・`functions[].refs` などの入れ子の `refs` に同じ型の関連を持つため、入れ子の側を `related` へ対応づけられず、`trace_related` でたどれない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

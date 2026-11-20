# metadata の `**.` で集める列を、集めた結果が空の文書でも列の欠けに数えない

## 概要

`documents[].metadata` に `**.` で始まる列（どの深さの列もまとめて取り出す対応）を記載した配信元で、集めた結果が空の文書を `metadata` の列の欠けに数えないようにする。
記載漏れの無い配信元なら、`check_project`・`describe` の警告・起動時の警告のログの列の欠けが 0 件になる。

## 背景

[Issue #211](https://github.com/shuhei1101/project-index/issues/211) の不具合。
`related: "**.refs[]"`（[Issue #98](https://github.com/shuhei1101/project-index/issues/98) の対応）を記載した配信元で、`refs` を 1 つも持たない文書が列の欠けに数えられる。
shuhei1101/ai-monitor の配信元では `missing_refs` が 842 件になり、全てが `related（**.refs[]）` だった。

[src/project_index/features/documents/fields.py](https://github.com/shuhei1101/project-index/blob/d1402c9/src/project_index/features/documents/fields.py#L507-L511) の `missing_ref_fields` は、項目の取得が `None` を返却した列を全て欠けにする。
`**.` の対応は、どの深さにも列が無い文書（関連を持たない設計書）でも `None` を返却する。

[shuhei1101/ai-monitor#3490](https://github.com/shuhei1101/ai-monitor/issues/3490) で、配布先の `check_project` の索引の同期を 0 件にそろえる反映作業を配るため、`**.refs[]` の対応を持つ配信元でも 0 件にできる必要がある。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理・変更箇所の由来 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

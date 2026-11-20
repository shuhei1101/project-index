# search_docs の filter と group_by で、配列の中のオブジェクトのキー（uses[].id など）で絞れるようにする

## 概要

エージェントが `search_docs` の `filter` と `group_by` で、配列の中のオブジェクトのキー（`uses: [{id: compare}]` の `id`）の値で、文書を完全一致で絞り、値ごとに集計できるようにする。

## 背景

[Issue #217](https://github.com/shuhei1101/project-index/issues/217) の要望。
1 ファイル 1 文書の YAML を一時の配信元で配信して確認したところ、オブジェクトのキー（`category.id`）はスキーマにキーを定義すると絞れたが、配列の中のオブジェクトのキーは次のとおり使用できなかった。

| 指定 | 結果 |
| --- | --- |
| `field: uses.id` | 0 件 |
| `field: uses[].id` | 「知らない項目です」のエラー |
| `field: uses`・`op: contains` | 部分一致になり、`compare` が `compare-x` にも該当する |
| `group_by: uses.id` | 全ての文書が「（なし）」 |

文書のストアの項目のパスの読み取り（`get_field`）は `uses[].id` を既に解釈できるが、検索で使用できる項目の一覧（`known_fields`）はスキーマの配列の要素のキーを `uses.id` として記載し、`uses[].id` を記載していない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

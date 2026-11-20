# search_docs などの使える項目に、スキーマの allOf・anyOf・oneOf と循環する $ref の先のキーを含める

## 概要

エージェントが `search_docs` などの `filter`・`order_by`・`group_by`・`fields` で、種類のスキーマの `allOf`・`anyOf`・`oneOf` と循環する `$ref` の先で定義した項目を指定できるようにする。

## 背景

[Issue #221](https://github.com/shuhei1101/project-index/issues/221) の要望。
作業 PR [#219](https://github.com/shuhei1101/project-index/pull/219) のレビューで、対象外の逸脱として報告された（[報告のコメント](https://github.com/shuhei1101/project-index/pull/219#discussion_r4640666650)）。

使える項目の一覧（`known_fields`）を作る `_walk` は、スキーマの `properties` と `items` だけをたどる。
[453989b](https://github.com/shuhei1101/project-index/commit/453989b) で、`$ref` を解決した後のスキーマ（`resolve_schema_refs` の結果）を `known_fields` に指定して確認した結果は次のとおり。

| スキーマの記載方法 | 項目の例 | 結果 |
| --- | --- | --- |
| `items: {$ref: '#/$defs/use'}` | `uses[].id` | 使用できる（文書のストアが `$ref` を参照先の中身に置き換えてから指定する） |
| `category: {$ref: '#/$defs/cat'}` | `category.id` | 使用できる（同上） |
| 最上位の `allOf: [{properties: {top: …}}]` | `top` | 知らない項目 |
| `a: {allOf: [{properties: {x: …}}]}` | `a.x` | 知らない項目 |
| `b: {anyOf: [{properties: {y: …}}, {type: null}]}` | `b.y` | 知らない項目 |
| 循環する `$ref`（`$defs.node.properties.children.items: {$ref: '#/$defs/node'}`） | `tree.children[].name` | 知らない項目（循環する参照は `$ref` のまま残る） |

knowledge のスキーマ（`schemas/rule.schema.yaml` など）は、最上位の `allOf` で共通のメタデータのスキーマを `$ref` で参照している。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

# worktree を指した write_docs・search_docs・trace_related を、worktree の project-index.yaml の行のスキーマの参照とメタデータの対応で検査・読み取りする

## 概要

エージェントが worktree の `project-index.yaml` で文書の行のスキーマの参照（`schema.ref`）やメタデータの対応（`metadata`）を変えたとき、その worktree を指した `write_docs`・`search_docs`・`trace_related` が、変えた後の行で文書を検査・読み取りできるようにする。

## 背景

[Issue #175](https://github.com/shuhei1101/project-index/issues/175) の不具合。
配信元 dev-docs の作業 PR [shuhei1101/dev-docs#280](https://github.com/shuhei1101/dev-docs/pull/280) で、worktree の設計書の行の `schema.ref` を `design-schemas/v8.4.0` から `design-schemas/v9.2.2` へ上げ、`metadata` に `related: refs` を追加した後も、次のとおり `default_ref` の設定で動いた。

- `write_docs`: v9.2.2 で関連の要素になった要素の中の `refs` を、v8.4.0 の `$defs/ref` で検査して弾く
- `search_docs`（`fields: [related]`）・`trace_related`（`direction: in`）: 設計書の `refs` を関連として返却しない

worktree の設定に追加した行の扱いは [#35](https://github.com/shuhei1101/project-index/issues/35)（`create` で追加した種類を参照する）と [#134](https://github.com/shuhei1101/project-index/issues/134)（読み取りで追加した行の文書を返却する）で修正したが、既存の行の `schema.ref` と `metadata` を worktree の値で参照することは扱っていない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・変更箇所の由来 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

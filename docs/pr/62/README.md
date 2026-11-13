# 文書のメタデータの visibility を共通のキーに追加し、読み取り API の文書の一覧・文書の取得で値を返却する

## 概要

画面のサーバーが、読み取り API の文書の一覧と文書の取得から、文書の公開範囲 `visibility` の値を受け取れるようにする。

## 背景

[Issue #57](https://github.com/shuhei1101/project-index/issues/57) の要望。[作業 PR #54](https://github.com/shuhei1101/project-index/pull/54) のスコープ外から切り出した。
`METADATA_KEYS` に `visibility` が無いため、`resolve_metadata` は文書の `visibility` をメタデータに入れず、文書の一覧（IF-24）の `documents[].visibility` と文書の取得（IF-25）の `metadata.visibility` は常に `null` になる。
IF-24・IF-25 の応答の例は `visibility` に値を持ち、設計書と実装が食い違っている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

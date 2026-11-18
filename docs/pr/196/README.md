# 配信元の設定で書き込み時の日時を付けないようにし、body_file の列を持たない要素を本文なしの文書として配信する

## 概要

利用者が、`created`・`updated` を持たないスキーマの Git 管理外の配信元へ `write_docs` で書き込め、`body_file` の行で本文のファイルを持たない要素も文書として参照・更新できるようにする。

## 背景

[Issue #195](https://github.com/shuhei1101/project-index/issues/195) の要望。MindStella のワークスペース（Git 管理外。`records: items`・`body_file: body`・スキーマは `additionalProperties: false`）を project-index で参照・書き込みできない（[shuhei1101/mindstella#583](https://github.com/shuhei1101/mindstella/issues/583)）。

- `write_docs` は Git 管理外の配信元で書き込む要素に `created`・`updated` を追加してからスキーマで検査するため、この 2 つのキーを許可しないスキーマでは全ての作成・更新が検査に通らない。配信元の設定に付けない指定が無い
- `body_file` の行で列の値を持たない要素も `missing_body_file` として配信から除くため、本文を持たない 301 件を参照・更新できず、`search_docs` の結果に除いた要素の数だけ警告の行が並ぶ

2 点とも project-index は設計書のとおりに動いている。完了したら後続の shuhei1101/mindstella#583 に着手できる旨を伝える。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・変更箇所の由来 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

# 端末の設定の配信元を、1 行ずつバージョンを照合して追加・変更・削除する API を追加する

## 概要

端末のほかのプロセス（MindStella など）が、ほかの行と設定の画面の保存を壊さずに、端末の設定の配信元の行を 1 行ずつ追加・変更・削除できるようにする。

## 背景

[Issue #10](https://github.com/shuhei1101/project-index/issues/10) の要望。
MindStella はワークスペースを作るたびに配信元の行を 1 行追加し、クローズで `outside_read: false`、削除で行の削除をする。
端末の設定の API は [#14](https://github.com/shuhei1101/project-index/issues/14)（[#15](https://github.com/shuhei1101/project-index/pull/15)）で dev-docs から移り、1 行の追加（`POST /settings/sources`）と、`outside_read` を含む取得が入った。
[#9](https://github.com/shuhei1101/project-index/issues/9)（[#22](https://github.com/shuhei1101/project-index/pull/22)）で、丸ごとの保存（`PUT /settings/sources`）は送信しなかったキーをファイルの今の値で残すようになった。
1 行の変更・削除はまだ無く、丸ごとの保存はほかのプロセスが書き換えた行を上書きしても、どちらの側も気づけない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

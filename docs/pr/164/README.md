# write_docs の unset で x-key の値で配列の要素を指し、要素の選び方を含むパスを unset.{パス} の違反にする

## 概要

エージェントが `write_docs` の `unset` で `x-key` の値で配列の要素を指して項目を削除でき、削除できないパスは違反で知れるようになる。

## 背景

[#162](https://github.com/shuhei1101/project-index/issues/162) の要望。
`unset` は `#` で始まる参照の型の項目のパスを受け付けず、要素の選び方（`[...]`・`**.`）を含むパスを指定すると `delete_field` の `InvalidArgumentError` がそのまま送信され、`set` のように `unset.{パス}` の違反にならない。
[#159](https://github.com/shuhei1101/project-index/pull/159) で `add_to`・`remove_from` を `x-key` の値で配列の要素へ解決する `resolve_array` を入れたときに、`unset` はスコープ外にした。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

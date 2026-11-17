# write_docs の参照の型の項目のパスで、x-key の値に `[` `]` を含む要素を指せるようにする

## 概要

エージェントが `write_docs` の `text_edits[].field`・`add_to`・`remove_from`・`unset` で、`x-key` の値に `[` `]` を含む要素（インターフェース定義の `request[operations[].fields]` など）を参照の型の項目のパスで指せるようになる。

## 背景

[#167](https://github.com/shuhei1101/project-index/issues/167) の要望。
[#165](https://github.com/shuhei1101/project-index/pull/165) のインターフェース定義設計で、`text_edits[].field` に `#request[operations[].fields].description` を指定すると `InvalidArgumentError`（`項目のパス request[operations[].fields].description の記載方法が誤っています`）で断られ、IF-6 の 4 か所を YAML の直接編集で直した（commit [66b5e9c](https://github.com/shuhei1101/project-index/commit/66b5e9c)）。
`fields.py` の参照の型の項目のパスの解釈（`REF_PATH_PATTERN`・`REF_PART_PATTERN`）が `[...]` の中の `]` を許さない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

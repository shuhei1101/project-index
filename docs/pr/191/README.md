# records を持たない行で create の配置先のファイル名に glob が残るときの修正案を修正する

## 概要

エージェントが `records` を持たない種類の文書を `write_docs` の `create` で作れなかったとき、`paths` の先頭のファイル名に glob が残っていることがエラーの修正案から分かるようにする。

## 背景

[Issue #189](https://github.com/shuhei1101/project-index/issues/189) の要望。
`new_document_path` は、`records` を持たない行で `paths` の先頭のファイル名の `*` を 1 つ ID に置き換えた後のファイル名に glob が残るとき（例: `docs/*-*.yaml`）も、修正案を `documents[].paths の先頭を glob にしてください` で返却する。
先頭は既に glob のため、この修正案からは修正方法が分からない。
[PR #188](https://github.com/shuhei1101/project-index/pull/188)（[Issue #187](https://github.com/shuhei1101/project-index/issues/187)）が `records` を持つ行の修正案を分けたときに、スコープ外として切り出した。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

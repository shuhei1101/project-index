# records を持つ行で create の配置先を決められないときの修正案を修正する

## 概要

エージェントが `records` を持つ種類の文書を `write_docs` の `create` で作れなかったとき、エラーの修正案から `documents[].paths` の先頭を glob を含まない 1 つのファイルにすればよいと分かるようにする。

## 背景

[Issue #187](https://github.com/shuhei1101/project-index/issues/187) の要望。
`new_document_path` は、配置先を決められないときの修正案を `records` の有無によらず `documents[].paths の先頭を glob にしてください` で返却し、`records` を持つ行では逆の内容になる。
gui-support の用語集の行（`records: terms`・`paths: ["docs/glossary/*.yaml"]`）では、この修正案から原因を特定できなかった（[shuhei1101/gui-support#159](https://github.com/shuhei1101/gui-support/issues/159)）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

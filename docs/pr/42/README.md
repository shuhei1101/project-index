# スキーマの $defs の中の相対パスの $ref を解決し、解決できない参照は理由の分かるエラーで返却する

## 概要

スキーマの `$defs` の中に相対パスの `$ref` を持つ種類の文書を、エージェントが `search_docs` で取得し、`write_docs` で部分更新できるようになる。
参照を解決できないときは、理由の分かるエラーを受け取れるようになる。

## 背景

[#36](https://github.com/shuhei1101/project-index/issues/36) の不具合（[shuhei1101/dev-docs#168](https://github.com/shuhei1101/dev-docs/issues/168) から移したもの）。
knowledge のフォルダ構成の設計書 `LAY-72-1` だけが、`search_docs` で `Error executing tool search_docs`、`write_docs` で `Error executing tool write_docs` の内容の無いエラーで止まる。

`LAY-72-1` の種類のスキーマ `schemas/design/layout.schema.yaml` は、`$defs/entry` の中に相対パスの `$ref`（`common.schema.yaml#/$defs/summary`）と、`$defs/entry` 自身への循環する `$ref` を持つ。
スキーマの参照の解決（`features/documents/schema.py` の `resolve_schema_refs`）は最上位の `$defs` を解決せずに残すため、相対パスの `$ref` が jsonschema へ渡り、検査で `Unresolvable: common.schema.yaml#/$defs/summary` が送出される。
MCP のツールは `ProjectIndexError` 以外の例外をそのまま送出するため、理由が利用者へ届かない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

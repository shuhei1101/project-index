# nav の auto.filter で、行の metadata で対応付けたキーを配信元の検査が使用できる項目として受け付ける

## 概要

配信元の設定の作成者が、`nav` の `auto.filter` に行の `metadata` で対応付けたキー（`category` など）を記載しても、配信元の検査が「知らない項目」と警告せず、dev-docs の画面と同じ条件を受け付ける。

## 背景

[Issue #146](https://github.com/shuhei1101/project-index/issues/146) の要望。
dev-docs の画面は [shuhei1101/dev-docs#262](https://github.com/shuhei1101/dev-docs/pull/262)（[shuhei1101/dev-docs#249](https://github.com/shuhei1101/dev-docs/issues/249)）で、行の `metadata` のキーを対応付けた列の型で使用できる項目に加え、項目の値も対応付けた列から取得するように修正した。
project-index の `nav_warnings`・`write_nav` が使用する項目の一覧（`known_fields`）は、行のスキーマと `METADATA_KEYS` だけから作り、行の `metadata` のキーを含めない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

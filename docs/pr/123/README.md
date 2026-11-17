# setup がプロンプトのスキーマを配置するとき、$ref 先の common.schema.yaml も配信元へ配置する

## 概要

`/project-index:setup` がプロンプトのスキーマを配信元へコピーするとき、`$ref` で指す共通の型 `common.schema.yaml` もコピーし、配信元でプロンプトのスキーマの `$ref` を解決できるようにする。

## 背景

[Issue #115](https://github.com/shuhei1101/project-index/issues/115) の不具合。
setup の手順 5 は `schemas/prompt.schema.yaml` だけを配信元の `schemas/` へコピーする。
そのスキーマの `$defs.example.properties.id` と `$defs.part.properties.id` は `common.schema.yaml#/$defs/id` を指すが、`common.schema.yaml` はコピーしないため、配信元で `$ref` を解決できない。
作業 PR [#114](https://github.com/shuhei1101/project-index/pull/114) の reviewer の対象外の逸脱の報告から起票された。#114 でコピー元は `schemas/` へ移った。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [プラグイン](./プラグイン.md) | プラグインの計画書 |

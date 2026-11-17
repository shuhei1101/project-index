# templates/files.schema.yaml を knowledge の knowledge-files.schema.yaml に合わせる

## 概要

setup のスキルが配信元へ書き出す管理用の YAML のスキーマを、knowledge の `knowledge-files.schema.yaml` と食い違わないようにする。

## 背景

[Issue #75](https://github.com/shuhei1101/project-index/issues/75) の要望。
作業 PR [#73](https://github.com/shuhei1101/project-index/pull/73) でフォルダ構成の設計書を作ったときに、管理用の YAML のスキーマが `schemas/` と `templates/` の 2 か所にあることを見つけた。
依存の [Issue #76](https://github.com/shuhei1101/project-index/issues/76) の作業 PR [#114](https://github.com/shuhei1101/project-index/pull/114) はマージ済みで、`schemas/files.schema.yaml` を削除し、このリポジトリの管理用の YAML の行を knowledge の [schemas/knowledge-files.schema.yaml](https://github.com/shuhei1101/knowledge/blob/5aa276ab2ad4c2f1db2a39d3712d2540d92adc37/schemas/knowledge-files.schema.yaml)（`design-schemas/v9.2.0`）の参照へ切り替えた。
残る [templates/files.schema.yaml](https://github.com/shuhei1101/project-index/blob/bd8a10107875ed36a301960c411c707043dc6cab/templates/files.schema.yaml) は、setup のスキルが配信元の `schemas/files.schema.yaml` へコピーする雛形で、単体・結合テストのフィクスチャも参照する。
knowledge のスキーマとは次が食い違う。

| キー | knowledge | templates |
| --- | --- | --- |
| `files[].id`・`files[].aliases`・`files[].inject_when`・`files[].category` | ✓ | |
| `checkpoint` | | ✓ |
| `files[].related[].to` の `description` | | ✓ |
| 直下の `description` の文言 | 短い | 1 行ずつの検査に `files.items` を適用する旨を含む |

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [プラグイン](./プラグイン.md) | プラグインの計画書 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

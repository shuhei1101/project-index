# dev-docs から移した文書を mdmark の書き方と表し方の優先順位に合わせる

## 概要

dev-docs から移した設計書と公開ドキュメントを、mdmark の書き方と表し方の優先順位（図 → 表 → 箇条書き → 文）に合わせ、`description` と本文の参照を今の規約の形にする。

## 背景

[Issue #18](https://github.com/shuhei1101/project-index/issues/18) の要望。
[PR #15](https://github.com/shuhei1101/project-index/pull/15) で dev-docs から移した文書は、このリポジトリの当時の決まりで記載しており、dev-docs の次の 3 件の決まりを当てていない。

| dev-docs の Issue | 決まり | `origin/develop` の状態 |
| --- | --- | --- |
| [shuhei1101/dev-docs#7](https://github.com/shuhei1101/dev-docs/issues/7) | 文書を `docs/` だけに置く構成 | 適用済み（設計書は `docs/{種類}/` の直下） |
| [shuhei1101/dev-docs#74](https://github.com/shuhei1101/dev-docs/issues/74) | YAML の設計書の `id` と、`{ID}#{項目のパス}` での参照 | ほぼ適用済み（設計書は `id` を持ち、参照は `id:` の形） |
| [shuhei1101/dev-docs#95](https://github.com/shuhei1101/dev-docs/issues/95) | mdmark の書き方と表し方の優先順位への移行 | 未適用 |

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの設計書と公開ドキュメントの計画書 |
| [プラグイン](./プラグイン.md) | プラグインの設計書の計画書 |

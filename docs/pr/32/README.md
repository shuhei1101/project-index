# ソースコードとテストの管理用の YAML を配信元に加え、設計書への related（implements・tests）を張る

## 概要

エージェントが `trace_related` で、設計書（モジュール構成・インターフェース定義）から実装とテストを辿れるようになる。

## 背景

[Issue #24](https://github.com/shuhei1101/project-index/issues/24) の要望。
配信元の設定 `project-index.yaml` の `documents[]` で `records: files` の行は、公開ドキュメント用の `docs/guide/files.yml` だけで、ソースコード・テストは配信していない。
[shuhei1101/dev-docs#95](https://github.com/shuhei1101/dev-docs/issues/95) の移行の手順 A-5「設計書とコードの関連」にあたり、[PR #23](https://github.com/shuhei1101/project-index/pull/23) のスコープ外から切り出した。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | `src/project_index/`・`tests/` の管理用の YAML と配信元の設定の計画書 |
| [プラグイン](./プラグイン.md) | プラグインのフックのコードの管理用の YAML の計画書 |

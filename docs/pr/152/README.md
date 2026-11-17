# 文書の ID の重なりを check_project と起動時の警告の索引の同期で通知する

## 概要

配信元を管理する利用者が、2 つの文書の ID が重なり片方が配信されない配置に `check_project` と起動時の警告で気づけるようになる。

## 背景

[Issue #144](https://github.com/shuhei1101/project-index/issues/144) の要望。作業 PR [#143](https://github.com/shuhei1101/project-index/pull/143)（起点 Issue [#142](https://github.com/shuhei1101/project-index/issues/142)）のスコープ外を切り出した。

- `store.py` の `_unique` は ID が先の文書と重なる文書を配信から除外し、`LoadResult.problems` に `reason: duplicate_id` を追加する
- `check_sync` は `problems` のうち `missing_body_file` だけを取得し、`duplicate_id` は `SyncReport` に入らない。`check_project`・起動時の警告・`status`・引数なしの `describe` のどれにも出ない

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

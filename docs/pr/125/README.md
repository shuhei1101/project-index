# 管理用の YAML に shared/deadline.py と test_deadline.py の行を追加する

## 概要

`src/files.yaml` に `project_index/shared/deadline.py` の行、`tests/files.yaml` に `unit/project_index/shared/test_deadline.py` の行を追加し、`check_project` の `unindexed_files` に数えられないようにする。

## 背景

[Issue #119](https://github.com/shuhei1101/project-index/issues/119) の要望。
2 つのファイルは [#82](https://github.com/shuhei1101/project-index/issues/82) で追加されたが、管理用の YAML に行が無く、公開ドキュメント『配信元を配信する』の「範囲のファイルを作った・削除した・改名したときは、そのたびに管理用の YAML の行を修正する」から外れている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

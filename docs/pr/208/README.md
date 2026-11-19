# history/blob.py とそのテストの行を管理用の YAML へ追加する

## 概要

`src/project_index/features/history/blob.py` と `tests/unit/project_index/features/history/test_blob.py` の行を管理用の YAML へ追加し、索引の同期を合わせる。

## 背景

[Issue #207](https://github.com/shuhei1101/project-index/issues/207) の要望。
`blob.py` とそのテストは #171 で追加されたが、`src/files.yaml`・`tests/files.yaml` に行が無く、`check_project` の `unindexed_files` が 2 件になっている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

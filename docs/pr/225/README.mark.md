# test_secrets.py の import の並びの lint 違反（ruff I001）を解消する

## 概要

develop で `uv run ruff check .` を実行したときの違反を 0 件にする。

## 背景

[Issue #224](https://github.com/shuhei1101/project-index/issues/224) の要望。
develop の [tests/unit/project_index/features/write/test_secrets.py](https://github.com/shuhei1101/project-index/blob/0151e10/tests/unit/project_index/features/write/test_secrets.py) は、`import pytest` と `from project_index.features.write.secrets import ...` の間に空行が無く、ruff の `unsorted-imports`（I001）が 1 件出る。
このファイルを最後に変えた commit は [c79ecf5](https://github.com/shuhei1101/project-index/commit/c79ecf5)（[PR #210](https://github.com/shuhei1101/project-index/pull/210)）。
作業 PR [#219](https://github.com/shuhei1101/project-index/pull/219) の lint のログで、reviewer が対象外の逸脱として報告した。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

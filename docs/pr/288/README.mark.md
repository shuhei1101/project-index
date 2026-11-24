# 配信元の 1 行の変更の結合テストの期待値を応答の writeApiConfig に追随させる

## 概要

結合テスト `test_normal_when_direct_commit_changed` の期待値を、配信元の設定の応答の `directCommit` が返す `writeApiConfig` に合わせ、develop で pass させる。

## 背景

[Issue #284](https://github.com/shuhei1101/project-index/issues/284) の不具合。
[#275](https://github.com/shuhei1101/project-index/pull/275) で `src/project_index/features/settings/route.py` の `_direct_commit_of` が `writeApiConfig` を返すようになったが、`tests/integration/server/test_patch_settings_source.py` の期待値が追随しておらず、結合テストの全件実行が develop で fail する。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

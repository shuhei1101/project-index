# 手元のテストの実行を observability の pytest のプラグインで観測基盤へ送信する

## 概要

開発者・エージェントが手元で回した project-index のテストの実行（層ごとの所要時間・成否・失敗の続き）を、observability の pytest のプラグインで観測基盤へ送信する。

## 背景

[Issue #185](https://github.com/shuhei1101/project-index/issues/185) の要望。
[shuhei1101/observability#109](https://github.com/shuhei1101/observability/issues/109)（作業 PR [shuhei1101/observability#113](https://github.com/shuhei1101/observability/pull/113)）で、依存を変えずに他のリポジトリの手元のテストの実行を観測基盤へ送信する pytest のプラグインと手順が決まった。
project-index のテスト実行方法 TP-1 の手元で回すコマンドは `uv run pytest` のままで、送信していない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |

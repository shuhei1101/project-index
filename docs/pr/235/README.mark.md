# MOD-67 の SettingsSourceAddRequest.source の型を SourceEntry にする

## 概要

モジュール構成 MOD-67 の `SettingsSourceAddRequest.source` の型を、実装とインターフェース定義 IF-32 に合わせて `SourceEntry` にする。

## 背景

[Issue #234](https://github.com/shuhei1101/project-index/issues/234) の要望。
[PR #233](https://github.com/shuhei1101/project-index/pull/233) の実装中に、MOD-67 の `SettingsSourceAddRequest.source` の型が `SettingsSourceRow`（取得の応答の行）と記載され、実装の `source: SourceEntry` と食い違うことが見つかった。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

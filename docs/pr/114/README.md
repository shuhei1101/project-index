# 設計書のスキーマを knowledge の参照へ切り替え、schemas/ の設計書のスキーマと配布する設定のスキーマを分ける

## 概要

`project-index.yaml` の設計書の種類と管理用の YAML の行のスキーマを knowledge の参照へ切り替えて取り込んだコピーを削除し、配布する設定のスキーマの配置先を決める。

## 背景

[Issue #76](https://github.com/shuhei1101/project-index/issues/76) の要望。
`schemas/` に、AI Monitor の配布物から取り込んだ設計書のスキーマのコピーと、配信元へ配る設定のスキーマ `project-index.schema.json` が混ざっている。
設定のスキーマは `src/project_index/schemas/` と `templates/` にもあり、`templates/common.schema.yaml` は `schemas/common.schema.yaml` と同じ名前で別の中身を持つ。
AI Monitor v0.4.0 の反映作業『各プロジェクトのスキーマの参照への移行』（[shuhei1101/ai-monitor#3430](https://github.com/shuhei1101/ai-monitor/issues/3430)）もこの作業 PR で行う。
依存の [#69](https://github.com/shuhei1101/project-index/issues/69) の作業 PR [#70](https://github.com/shuhei1101/project-index/pull/70) はマージ済み。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |
| [プラグイン](./プラグイン.md) | プラグインの計画書 |

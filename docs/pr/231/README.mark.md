# リポジトリの直下の project-index.yaml の 1 行目の $schema を project-index のスキーマへ向ける

## 概要

リポジトリの直下の `project-index.yaml` の 1 行目を、project-index の v0.2.0 のタグの `schemas/project-index.schema.json` を指す行にする。

## 背景

[Issue #26](https://github.com/shuhei1101/project-index/issues/26) の要望。[PR #19](https://github.com/shuhei1101/project-index/pull/19) で `dev-docs.yaml` から改名した直下の `project-index.yaml` の 1 行目は、まだ dev-docs のスキーマを指している。
`docs/guide/設定.md`・`docs/guide/配信元を登録する.md`・`docs/scenario/SC-5.yaml` は、1 行目を project-index のタグの `schemas/project-index.schema.json` を指す行にすると定めている。
`schemas/project-index.schema.json` を含むタグ v0.2.0 が [Issue #229](https://github.com/shuhei1101/project-index/issues/229) で打たれ、前提がそろった。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |

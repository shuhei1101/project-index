# 配信元の設定の files_guide の行の exclude から管理用の YAML に該当する *.yml を除外する

## 概要

配信元 project-index の `files_guide` の行が、`docs/guide/` の公開ドキュメントの Markdown を文書として配信する。

## 背景

[Issue #33](https://github.com/shuhei1101/project-index/issues/33) の不具合。
`project-index.yaml` の `files_guide` の行は `paths` が `docs/guide/files.yml` で、`exclude` に `"*.yml"` を持つ。
`DocumentTable.matches` は `exclude` に該当するファイル名を行の文書にしないため、管理用の YAML `files.yml` 自身が読まれず、`files_guide` の文書が 0 件になる。
[PR #32](https://github.com/shuhei1101/project-index/pull/32) のレビューで、`src` の行の同じ誤りと合わせて見つかった。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |

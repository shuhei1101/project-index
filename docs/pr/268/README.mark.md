# 直コミットで本文（@body）の書き換えを断りメタデータだけを許可する種類を配信元の設定で決められるようにする

## 概要

配信元の設定の `direct_commit` で、種類ごとに直コミットで本文（`body_file` の `@body`）を書き換えるのを断ってメタデータだけを許可できるようにし、断る種類の本文の書き換えを `write_docs`・`delete_docs` の `commit` と書き込みの API の直コミットで理由つきのエラーにする。

## 背景

[Issue #267](https://github.com/shuhei1101/project-index/issues/267) の要望（後続 [shuhei1101/knowledge#564](https://github.com/shuhei1101/knowledge/pull/564)）。
knowledge#564 で、dev-docs のメタデータの画面から管理用の YAML（`files.yaml`）の行のタグ・概要を修正できるように `records`・`body_file` の種類を `direct_commit.kinds[]` に追加すると、`set: {"@body": ...}` で行が指す本文のファイル（スキーマの原本・検査のスクリプト・`project-index.yaml`）もスキーマ・`validators[]` の検査なしで直コミットできてしまう（[レビューの指摘](https://github.com/shuhei1101/knowledge/pull/564#discussion_r4661451983)）。
[shuhei1101/dev-docs#310](https://github.com/shuhei1101/dev-docs/issues/310) の決定では、直コミットの対象はデータとメタデータで、テンプレートとスキーマは Issue と作業 PR を経る。
[978cc5d](https://github.com/shuhei1101/project-index/commit/978cc5d)（develop）の `direct_commit` は `branch`・`branches`・`kinds`（文字列の並び）だけを持ち、直コミットの許可を種類の単位でしか決められない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 種類ごとに本文の直コミットを断る計画書 |

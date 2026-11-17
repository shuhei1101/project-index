# check_project で 2 つの documents の行が同じファイルを文書にする配置を検出し、項目のパスで配列の要素を x-key の値で指せるようにする

## 概要

配信元を管理する利用者が、2 つの documents の行が同じファイルを文書にする配置に `check_project` と起動時の警告で気づけるようになる。
エージェントが、`write_docs` の `text_edits` で配列の要素を位置でなく `x-key` の値で指し、要素の中の文字列の項目を部分更新できるようになる。

## 背景

束の親 [Issue #142](https://github.com/shuhei1101/project-index/issues/142) の要望。子は [#136](https://github.com/shuhei1101/project-index/issues/136) と [#138](https://github.com/shuhei1101/project-index/issues/138)。

- #136: 作業 PR [#131](https://github.com/shuhei1101/project-index/pull/131)（起点 Issue [#124](https://github.com/shuhei1101/project-index/issues/124)）は `content/prompts/` の重なりだけを setup で避け、一般の重なりの検出をスコープ外として切り出した。今の `check_sync` は文書の ID の重なり（`duplicate_id`）も行どうしの同じファイルも報告しない
- #138: 作業 PR [#137](https://github.com/shuhei1101/project-index/pull/137)（起点 Issue [#128](https://github.com/shuhei1101/project-index/issues/128)）のモジュール構成設計で行き当たった。今の項目のパスは配列の要素を位置（`[n]`）か「キーが真の要素」（`[{キー}]`）でしか指せず、`functions[apply_migration].process` は文字列に該当しない

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

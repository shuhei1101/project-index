# write_docs に文書の改名と、複数の文書・項目にまたがる単語の一括置換の操作を追加する

## 概要

エージェントが `write_docs` で、文書の改名（ID・ファイル名の変更と参照元の追随）と、複数の文書・項目にまたがる単語の一括置換を、YAML を直接編集せずに行えるようになる。

## 背景

[Issue #150](https://github.com/shuhei1101/project-index/issues/150) の要望。起票元は [shuhei1101/ai-monitor#3239](https://github.com/shuhei1101/ai-monitor/issues/3239)。

- `write_docs` の `op` は `create`・`update`・`replace` だけで、改名と文書をまたぐ置換は `git mv` とスクリプトでの YAML の直接編集で回避している（[shuhei1101/claude-balancer#239](https://github.com/shuhei1101/claude-balancer/issues/239)・[#341](https://github.com/shuhei1101/claude-balancer/issues/341)・[shuhei1101/mdmark#394](https://github.com/shuhei1101/mdmark/issues/394)）
- `text_edits` は 1 つの文書の 1 つの文字列の項目への操作で、配列・辞書の項目を丸ごと指すと `文字列ではない項目は置き換えられません` で止まる
- AI Monitor の書き込みのツールは改名と一括置換を持っていたが（[shuhei1101/ai-monitor#2778](https://github.com/shuhei1101/ai-monitor/pull/2778)）、設計書の MCP を移したときに無くなった

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

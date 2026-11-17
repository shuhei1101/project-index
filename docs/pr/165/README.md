# write_docs の rename・replace_text を、records・body_file の行の本文のファイルの中の旧 ID・旧パスと単語にも適用する

## 概要

エージェントが `write_docs` の `rename`・`replace_text` で、`records`・`body_file` の行の文書の本文のファイル（Markdown など）の中の旧 ID・旧パスの参照と単語も、YAML の項目と同じ 1 回の呼び出しで書き換えられるようになる。

## 背景

[Issue #163](https://github.com/shuhei1101/project-index/issues/163) の要望。[作業 PR #157](https://github.com/shuhei1101/project-index/pull/157)（起点 [Issue #150](https://github.com/shuhei1101/project-index/issues/150)）のスコープ外の行から切り出した。

- #157 で追加した `rename`・`replace_text` は文書の YAML の項目だけを書き換え、IF-6 の制約「改名の参照元」「一括置換の対象」で本文のファイルの中を対象外と定めた
- 本文のファイルはスキーマ・検査に合格させない自由な形式で、#157 では本文の中の参照の書き方を決められなかった
- そのため、改名で本文のファイルの中の `id:{旧 ID}` のリンク・相対パスのリンクが古いまま残り、一括置換で本文のファイルの中の単語が置換されない

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

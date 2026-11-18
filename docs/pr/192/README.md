# write_docs の text_edits の field の違反に、# で始まる参照の型の項目のパスと位置での指し方を案内する fix を付ける

## 概要

エージェントが `write_docs` の `text_edits[].field` で項目を指し損ねたとき、違反の `fix` から `#` で始まる参照の型の項目のパス・位置での指し方・`set` などへの切り替えを知り、YAML を直接編集せずに書き直せるようになる。

## 背景

[Issue #190](https://github.com/shuhei1101/project-index/issues/190) の要望。起票元は [shuhei1101/ai-monitor#3192](https://github.com/shuhei1101/ai-monitor/issues/3192) と [shuhei1101/ai-monitor#3627](https://github.com/shuhei1101/ai-monitor/pull/3627)。

- `text_edits[].field` に `x-key` を持つ配列の要素を `#` なしの `functions[sendForm].summary` や `functions.main.side_effects` で渡すと、`文字列ではない項目は置き換えられません` か `項目のパス … の記載方法が誤っています` が返る
- どちらの違反も `fix` を持たず、11-01〜11-18 の `write_docs` のエラー 3,500 回のうち約 260 回がこの型だった
- エラーの後に設計書の YAML を直接編集した例がある（[shuhei1101/mindstella#473](https://github.com/shuhei1101/mindstella/issues/473)・[shuhei1101/dev-docs#219](https://github.com/shuhei1101/dev-docs/issues/219)）

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

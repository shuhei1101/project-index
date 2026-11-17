# migrate・端末の設定の保存・write_nav・確認の時点の記録の書き出しで元のファイルの配列の字下げを保つ

## 概要

`project-index migrate`・端末の設定の保存・`write_nav`・確認の時点の記録で YAML のファイルを書き換えたとき、変えていない行の配列の字下げを元のファイルのまま保つ。

## 背景

[Issue #128](https://github.com/shuhei1101/project-index/issues/128) の要望。
作業 PR [#121](https://github.com/shuhei1101/project-index/pull/121)（起点 Issue [#120](https://github.com/shuhei1101/project-index/issues/120)・[#118](https://github.com/shuhei1101/project-index/issues/118)）で往復編集の書き出し `dump_roundtrip` に引数 `original`（元の文字列）を追加し、`write_docs`・`delete_docs` だけで渡した。
ほかの呼び出し元は `original` を渡さないため、元のファイルが `- ` を字下げ無しで並べていると、変えていない行まで字下げが変わる。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

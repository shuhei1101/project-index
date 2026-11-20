# write_docs の set で、x-key の値で指した配列の要素に今は無いキーを追加できるようにする

## 概要

エージェントが、`write_docs` の `set` で、x-key を持つ配列の要素を x-key の値で指して、その要素に今は無いキーを追加できるようにする。

## 背景

[Issue #222](https://github.com/shuhei1101/project-index/issues/222) の要望。`text_edits`・`add_to`・`remove_from`・`unset` では `#` で始めて x-key の値で要素を指せるが、`set` は `functions[createParser].usecase`・`#functions[createParser].usecase` のどちらも「`**`・`[]`・`[{キー}]` を含む項目のパスには書き込めません」で断る。
位置で指す `functions[0].usecase` だけが通るため、エージェントは要素の並びを数えるか、設計書の YAML を直接編集している（[shuhei1101/ai-monitor#3623](https://github.com/shuhei1101/ai-monitor/issues/3623)・[shuhei1101/mdmark#668](https://github.com/shuhei1101/mdmark/issues/668)）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理・変更箇所の由来 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

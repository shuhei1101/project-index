# 画面のサーバーから、直コミットつきで文書を書き込める経路と、その呼び出しの許可の決め方を追加する

## 概要

dev-docs の画面のサーバーが、`write_docs` と同じ検査に合格させてから配信元の文書を書き込み、複数の文書の修正を 1 回の直コミット（コミット・プッシュ）にまとめられるようにする。

## 背景

[Issue #252](https://github.com/shuhei1101/project-index/issues/252) の要望。後続の [shuhei1101/dev-docs#310](https://github.com/shuhei1101/dev-docs/issues/310) で、dev-docs の画面から配信元のメタデータを修正し、溜めた修正を直コミット（[#209](https://github.com/shuhei1101/project-index/issues/209)）でまとめてコミット・プッシュする。
今の読み取り API（[src/project_index/features/read/route.py](https://github.com/shuhei1101/project-index/blob/9541266/src/project_index/features/read/route.py)）は GET だけで、書き込みは文書の MCP の `write_docs`・`delete_docs` にしか無い。
直コミットを呼べるかは [src/project_index/features/access/service.py](https://github.com/shuhei1101/project-index/blob/9541266/src/project_index/features/access/service.py) の `committable_kinds` が作業場所を端末の設定の glob に照らして決め、作業場所を持たない要求には空を返却するため、画面のサーバーからは直コミットを呼べない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 画面のサーバーからの書き込みの経路と直コミットの許可の計画書 |

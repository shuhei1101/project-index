# write_docs の add_to が x-key の値の重なりを確かめずに要素を追加することと、要素を置き換える手順を IF-6 とガイドに記載する

## 概要

エージェントが IF-6 とガイド『文書の MCP』で、`write_docs` の `add_to` が `x-key` を持つ配列に既にある `x-key` の値の要素を指定しても末尾へ追加することと、要素を置き換えるときの手順を参照できるようになる。

## 背景

[#180](https://github.com/shuhei1101/project-index/issues/180) の要望。
[#179](https://github.com/shuhei1101/project-index/pull/179)（起点 Issue [#177](https://github.com/shuhei1101/project-index/issues/177)）のスコープ外として切り出された。
`src/project_index/features/write/apply.py` の `_add_to` は重なりを確認せずに末尾へ追加し、IF-6 の `operations[].add_to` は「配列の項目の末尾へ要素を追加する」とだけ定めている。
同じ `x-key` の値の要素が複数ある状態は IF-6 の参照の型の項目のパス（`[{値}#{順番}]`）とガイドが受け付けているため、[#180 の扱いの判断](https://github.com/shuhei1101/project-index/issues/180#issuecomment-6955469337)で、違反にせず今の振る舞いと置き換えの手順を記載すると決定した。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

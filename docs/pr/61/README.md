# 配信元の ID の重なりで行を入れ替えたときに、除外した行の文書のキャッシュを破棄する

## 概要

起動時の配信元の行ごとの読み込みで、ID が重なる行を入れ替えたときに、除外した行の文書が返らないようにする。

## 背景

[Issue #37](https://github.com/shuhei1101/project-index/issues/37) の要望（[shuhei1101/dev-docs#136](https://github.com/shuhei1101/dev-docs/pull/136) の reviewer の任意の指摘から切り出し、dev-docs から移した）。
`registry.py` の `_publish` は、後の位置の行が先に読み込まれて配信された後に先の位置の行で ID を入れ替えても、文書のストアのキャッシュを破棄しない。
起動の `load` は `discard_source_caches` を通らないため、次の `reload` まで除外した行の文書を返却しうる。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

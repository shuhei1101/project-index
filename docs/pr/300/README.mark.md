# 語での検索の結果の文書ごとに、一致した行の数を返却する

## 概要

dev-docs の画面のサーバーが、語での検索（`GET /sources/{source}/search`）の結果の文書ごとに、本文の一致した行の数を受け取れるようにする。

## 背景

[Issue #299](https://github.com/shuhei1101/project-index/issues/299) の要望。
dev-docs の検索のダイアログで、結果を一致した行の数の多い順に並べ、行ごとに「一致 N 行」と出す（[shuhei1101/dev-docs#338](https://github.com/shuhei1101/dev-docs/issues/338)、作業 PR [shuhei1101/dev-docs#340](https://github.com/shuhei1101/dev-docs/pull/340)）。
今の応答の `items[].snippets` は文書ごとに 3 件までで（[src/project_index/features/read/search.py](https://github.com/shuhei1101/project-index/blob/c6da2b1308df0e1852d6800f279b1c8e85b224ec/src/project_index/features/read/search.py) の `SNIPPETS_PER_DOC`）、利用する側では一致した行の数を求められない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

# write_docs の remove_from で x-key を持つオブジェクトの配列から x-key の値で要素を削除し、削除できない値を違反にする

## 概要

エージェントが `write_docs` の `remove_from` で、`x-key` を持つオブジェクトの配列（インターフェース定義の `flows` など）の要素を `x-key` の値で指して削除できるようになる。削除できない値を渡したときは、何も変えずに `updated` を返すのではなく違反が返る。

## 背景

[#177](https://github.com/shuhei1101/project-index/issues/177) の要望。
[#173](https://github.com/shuhei1101/project-index/pull/173) のインターフェース定義設計で、IF-116-1 の `flows` から `remove_from: {flows: [{name の値}]}` で要素を削除しようとしたところ、`applied: true`・`status: updated` が返ったがファイルは変わらず、YAML を直接編集して回避した（[825a663](https://github.com/shuhei1101/project-index/commit/825a663)）。
`src/project_index/features/write/apply.py` の `_remove_from` は渡した値と等しい要素だけを除き、IF-6 の `operations[].remove_from` は `x-key` を持つオブジェクトの配列への指定の扱いを定めていない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

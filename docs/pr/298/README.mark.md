# write_docs の create で、id のキーを持たない種類の文書の ID を new_path から決める

## 概要

エージェントや管理画面が `write_docs` の `create` で、ID のキーを持たない種類（配信元の直下からのパスを ID にする種類）の文書を、`new_path` を指定して作成できるようにする。

## 背景

[Issue #297](https://github.com/shuhei1101/project-index/issues/297) の要望。
aituber の作業 PR [shuhei1101/aituber#292](https://github.com/shuhei1101/aituber/pull/292) が、管理画面と MCP のツールから立ち絵の定義 `portrait/{キャラクター ID}/definition.yaml`（種類 `portrait_definition`）を作成して develop へ直コミットし、この Issue が入るのを #292 のマージの前提にしている。
[#293](https://github.com/shuhei1101/project-index/issues/293) で `create` に `new_path` が入ったが、作成する文書の ID は `data` の ID か `ids.format` からだけ決定する（[src/project_index/features/write/service.py](https://github.com/shuhei1101/project-index/blob/9d54fdc389268bcacea56c26ec2b7da5b8b269e6/src/project_index/features/write/service.py) の `_new_id`）。
そのため、ID のキーを持たない種類は、操作の `id` を指定するとスキーマの検査（`'id' was unexpected`）で、省くと `ids.format` が無いことで断られ、どちらの呼び方でも作成できない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

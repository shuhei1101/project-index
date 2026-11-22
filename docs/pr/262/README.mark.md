# SQLite の表の行を読み取り専用の文書として配信し、タグの検索と別名の照合の対象にする

## 概要

配信元の設定の `documents[]` の行で SQLite の表（か SQL のビュー）を指すと、その表の行が読み取り専用の文書として配信され、エージェントが `search_docs`・`describe`・`list_match_words` の 1 回の検索でアプリの SQLite のデータも探せるようになる。

## 背景

[Issue #255](https://github.com/shuhei1101/project-index/issues/255) の要望。
配信元の文書は、`documents[]` の行ごとにフォルダの中のファイル（1 ファイル 1 文書か、`records` の配列の 1 要素 1 文書）からだけ集めている。
アプリが SQLite に持つデータ（aituber の `aituber.db` のゲーム実況の行・AI Monitor の連絡ボード）はタグの検索と別名の案内の対象にならず、エージェントは project-index とアプリの MCP のツールで 2 回検索している。
索引のサーバーで SQLite を扱うのは、今は会話ごとの記録（`features/seen/store.py`）だけで、文書として配信する行は無い。

書き込みは今のまま各アプリの MCP のツールで行い、project-index は読み取り専用で配信する（Issue の決定事項）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

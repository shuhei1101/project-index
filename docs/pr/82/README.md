# 文書の MCP の時間切れの応答と書き込みの成否を一致させ、書き込まなかった理由を返却し、worktree を指定した読み取りを上限の内に返却する

## 概要

エージェントが `write_docs` の応答から書き込めたかと書き込めなかった理由を判断でき、`worktree` を指定した `search_docs` の結果をクライアントの時間切れの前に受け取れるようにする。

## 背景

[Issue #81](https://github.com/shuhei1101/project-index/issues/81) の要望。
依頼元の [ai-monitor#3475](https://github.com/shuhei1101/ai-monitor/pull/3475) で文書の MCP の時間切れを切り分けた結果、検査のスクリプトの所要時間とは別に、project-index の本体で次の 3 つが起きている。

- `write_docs` がクライアント側で `The operation timed out.` になった後もサーバーが処理を続けて書き込む（[mdmark#422](https://github.com/shuhei1101/mdmark/pull/422)）
- 検査のスクリプトが制限時間で止められた場合と違反で書き込まなかった場合に、`Error executing tool` だけが返り理由が分からない（[knowledge#327](https://github.com/shuhei1101/knowledge/pull/327)）
- `worktree` を指定した `search_docs` が、検査のスクリプトを呼ばない読み取りでも時間切れになる（[mdmark#494](https://github.com/shuhei1101/mdmark/pull/494)・[mdmark#485](https://github.com/shuhei1101/mdmark/pull/485)）

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

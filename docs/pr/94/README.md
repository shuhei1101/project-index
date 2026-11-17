# 配信元ごとの最初の問い合わせの時間切れを解消し、reload の応答の時点と読み直しの完了を status で見分けられるようにする

## 概要

画面のサーバーが配信元ごとの最初の問い合わせを 2 回目以降と同じ程度の時間で受け取り、管理の MCP の呼び出し元が `reload` の応答の時点と読み直しの完了を見分けられるようにする。

## 背景

束の親 [Issue #91](https://github.com/shuhei1101/project-index/issues/91) の要望で、次の 2 件を 1 本の作業 PR で扱う。

- [#85](https://github.com/shuhei1101/project-index/issues/85): dev-docs の画面で配信元を開くと 1 回目だけ 13〜48 秒かかる（[dev-docs#225](https://github.com/shuhei1101/dev-docs/issues/225)）。[dev-docs#230](https://github.com/shuhei1101/dev-docs/pull/230) の計測で、時間の大半は project-index が配信元ごとの最初の問い合わせで行うリビジョンの書き出し（`git archive`）で、`git archive` の 20 秒の上限を超えて 500 を返すこともあった
- [#86](https://github.com/shuhei1101/project-index/issues/86): 管理の MCP の `reload` が全ての配信元の検査を終えるまで応答せず（実測 14〜24 分）、その間 `status` で読み直しの最中か済んだかを見分けられない（依頼元 [claude-balancer#311](https://github.com/shuhei1101/claude-balancer/pull/311)）

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

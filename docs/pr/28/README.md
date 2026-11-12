# 端末の負荷が高い間にリビジョンの書き出しの git archive が待ち時間の上限で止まらないようにする

## 概要

端末の負荷が高い間も、エージェントが `search_docs`・`write_docs` で配信元の文書を読み書きできるようにする。

## 背景

[Issue #27](https://github.com/shuhei1101/project-index/issues/27) の要望。
作業 PR [#19](https://github.com/shuhei1101/project-index/pull/19) の反映作業 `端末の設定の配信元のパスの修正` の確認の工程で、`search_docs` が ARCH-1 を返さず止まった（[tester の報告](https://github.com/shuhei1101/project-index/issues/16#issuecomment-6818377197)）。
ユーザーがローカルのセッションで再実行したときも 1 回目は同じ箇所で failed になり、原因は、配信元の develop の commit を書き出す `git archive` が端末の負荷（load average 18）で git の待ち時間の上限 8 秒（`GIT_TIMEOUT_SEC`）を超えたことと分かった（[ユーザーの報告](https://github.com/shuhei1101/project-index/pull/23#discussion_r4550249890)）。
再実行すると ok になり、反映作業はユーザーの実行で済んでいる。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

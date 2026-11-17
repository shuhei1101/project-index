# 起動の直後のリビジョンの書き出しの最中でも、開いた配信元の文書の一覧が待たされずに返るようにする

## 概要

起動の直後でも、利用者が dev-docs の画面で開いた配信元の文書の一覧が、ほかの配信元のリビジョンの書き出しを待たずに短い時間で返るようにする。

## 背景

[Issue #145](https://github.com/shuhei1101/project-index/issues/145) の要望。依頼元は [shuhei1101/dev-docs#225](https://github.com/shuhei1101/dev-docs/issues/225) の作業 PR [shuhei1101/dev-docs#262](https://github.com/shuhei1101/dev-docs/pull/262)。
[#94](https://github.com/shuhei1101/project-index/pull/94)（[#85](https://github.com/shuhei1101/project-index/issues/85)）で、起動の後に配信元ごとの `default_ref` の commit を裏で順に書き出すようにした。
その後の develop で 14 件の配信元を起動の直後に開くと、全ての書き出しが終わる約 90 秒後までの間、文書の一覧が 17〜45 秒以上待たされ、dev-docs の画面が 45 秒で打ち切った配信元があった。書き出しが終わった後は、どの配信元も数秒で返った。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・変更箇所の由来 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

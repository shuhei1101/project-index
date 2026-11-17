# 起動の直後の文書の一覧の読み込みの完了待ち・git archive と、文書の多い配信元の読み込みの時間を短くする

## 概要

利用者が dev-docs の画面で開いた配信元の文書の一覧が、起動の直後でも、文書の多い配信元でも、短い時間で返るようにする。

## 背景

束の親 [Issue #170](https://github.com/shuhei1101/project-index/issues/170) の要望で、子は [#160](https://github.com/shuhei1101/project-index/issues/160) と [#161](https://github.com/shuhei1101/project-index/issues/161)。
どちらも作業 PR [#147](https://github.com/shuhei1101/project-index/pull/147)（[#145](https://github.com/shuhei1101/project-index/issues/145)）の PoC 検証（PoC PR [#153](https://github.com/shuhei1101/project-index/pull/153)）で見つかった、裏の検査との競合を除いても残る待ちで、#147 のスコープ外にした。

- #160: 起動の直後に最初に開いた配信元 dev-docs の文書の一覧が 16.7〜17.3 秒かかる。配信元の読み込みの完了待ち（`registry.wait_for`）が 6〜10 秒、要求の中のリビジョンの書き出し（`SnapshotStore.checkout` の `git archive`）が 6〜8 秒
- #161: 配信元 ai-monitor（1,212 文書）の文書の一覧が 1 回目に約 12 秒（文書の読み込みの CPU 時間が占める）、キャッシュに載った 2 回目でも画面で 6〜9 秒かかる

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・変更箇所の由来 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

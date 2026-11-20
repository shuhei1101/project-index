# 端末の設定の API の追加・保存・1 行の変更で sources[].direct_commit をファイルの行へ書き出す

## 概要

端末の設定の API で配信元の行を追加・保存・変更したとき、行の `direct_commit` を端末の設定のファイルへ書き出し、API で登録した配信元にも直コミットを呼べる作業場所を設定できるようにする。

## 背景

[Issue #232](https://github.com/shuhei1101/project-index/issues/232) の要望。
`POST /settings/sources` に `direct_commit.scope` を持つ行を送信すると `201` が返り配信元は `serving` になるが、`~/.config/project-index/settings.yaml` のその行に `direct_commit` が記載されず、`direct_commit.scope` が既定の `[]` のままになる。
[PR #210](https://github.com/shuhei1101/project-index/pull/210) で端末の設定の行に `direct_commit` を追加したとき、端末の設定の API の書き出し（`_to_yaml_row`）・送信しなかったキーの補完（`_fill_unsent`）・1 行の変更のキー（`SourcePatch`）が追随していない。
shuhei1101/knowledge#514 の反映作業「ネットミームの配信元の登録」が、この修正のリリースを待って止まっている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理と変更箇所の由来 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

# 配信元の設定の取得の API が、本文の直コミットを断る種類を返却する

## 概要

dev-docs の画面のサーバーが、読み取り API の配信元の設定の取得（`GET /sources/{source}/config`）で、配信元ごとの本文の直コミットを断る種類を取得できるようになる。

## 背景

[#279](https://github.com/shuhei1101/project-index/issues/279) の要望。
[shuhei1101/dev-docs#321](https://github.com/shuhei1101/dev-docs/issues/321) で、dev-docs のメタデータの画面に、本文の直コミットを断る種類（[#268](https://github.com/shuhei1101/project-index/issues/268) の `direct_commit.kinds[]` の `{id, body: false}`）の文書の本文の編集を出さないようにする。
今の project-index では、本文の直コミットを断る種類を返却するのは文書の MCP の `describe` だけで、画面のサーバーが呼ぶ読み取り API と端末の設定の API には無い。
そのため画面のサーバーは、書き込みの API が 422 で断る本文の編集を、送信する前に判定できない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理と影響する UC 一覧 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

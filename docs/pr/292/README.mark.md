# ref を指定した読み取りで、そのリビジョンにだけある文書を 500 にせず返却する

## 概要

画面のサーバーが読み取り API の文書の取得で `ref` を指定したとき、そのリビジョンにだけある文書も 200 で取得できるようにする。

## 背景

[Issue #291](https://github.com/shuhei1101/project-index/issues/291) の不具合。
`GET /sources/aituber/docs/docs/scenario/SC-164-54.yaml?ref=feat%2Fvideo%2Fadd-script-and-adlib` が `FileNotFoundError` で 500 を返却した（2026-11-25 19:46:52、develop [3cf1f4d](https://github.com/shuhei1101/project-index/commit/3cf1f4d)）。
文書の取得は、文書が更新日時を持たないとき作業ツリーのファイルを stat して更新日時にするため、作業ツリーに無いファイルで失敗する。

## 計画書

| ファイル | 中身 |
| --- | --- |
| `要件.mark.md` | 要望の整理と変更箇所の由来 |
| `索引のサーバー.mark.md` | 索引のサーバーの計画書 |

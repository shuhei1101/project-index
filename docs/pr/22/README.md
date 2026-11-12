# 端末の設定の保存で、送信されなかった配信元の行のキー（outside_read など）をファイルの今の値で残す

## 概要

dev-docs の設定の画面で配信元を保存しても、画面が送信しなかったキー（`outside_read` など）が `settings.yaml` から消えないようにする。

## 背景

[Issue #9](https://github.com/shuhei1101/project-index/issues/9) の不具合の報告。
設定の画面は保存のときに、配信元の行を `id`・`config`・`enabled`・`scope` だけにして `PUT /settings/sources` で全件を送信する。
サーバーの `save_sources` は送信された行で `sources[]` を丸ごと置き換え、`outside_read` が既定の `true` の行にはキーを記載しないため、ファイルに `outside_read: false` を記載した行からキーが消え、作業範囲の外から参照できるようになる。
設定の API は [#14](https://github.com/shuhei1101/project-index/issues/14)（[#15](https://github.com/shuhei1101/project-index/pull/15)）で dev-docs から project-index へ移った。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

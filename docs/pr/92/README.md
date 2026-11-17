# 端末の設定の保存・1 行の追加で expectedVersion を必須にし、write_docs・delete_docs で records・body_file の本文のファイルを書き込む

## 概要

端末の設定の API を呼ぶ側が、取得した後に書き換えられた端末の設定を丸ごとの保存と 1 行の追加でも上書きしないようにする。
エージェントが、本文を別のファイルに持つ配信元（`records`・`body_file` の行）の文書を、本文のファイルを含めて `write_docs` で作成・置き換え・一部の書き換えをできるようにする。

## 背景

束の親 [Issue #89](https://github.com/shuhei1101/project-index/issues/89) の要望で、次の 2 件を 1 本で行う。

- [#60](https://github.com/shuhei1101/project-index/issues/60): [#29](https://github.com/shuhei1101/project-index/pull/29) で端末の設定の API に内容のバージョンの照合が入ったが、`PUT`・`POST /settings/sources` は dev-docs の設定の画面がバージョンを送信していなかったため、`expectedVersion` を送信したときだけ照合している。画面の送信は [shuhei1101/dev-docs#190](https://github.com/shuhei1101/dev-docs/issues/190) で済んだ
- [#83](https://github.com/shuhei1101/project-index/issues/83): `write_docs` は `records`・`body_file` の行の文書で `records` の要素だけを書き換え、`body_file` が指す本文のファイルを書き込まない。`delete_docs` も要素を除くだけで本文のファイルを残す。使う側の [shuhei1101/mindstella#540](https://github.com/shuhei1101/mindstella/pull/540) が、ワークスペースの資料の本文の書き込みを project-index へ移すために求めている

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

# テスト実行方法の run_runner で、起動した run を API で参照できるまで待ってから gh run watch を呼ぶ

## 概要

テスト実行方法の `run_runner` を実行した開発者が、起動した直後の run を 404 で取りこぼさずに、ランナーの集計の行を受け取れるようにする。

## 背景

[Issue #129](https://github.com/shuhei1101/project-index/issues/129) の要望。
テスト実行方法 TP-1 の TL-1・TL-2 の `run_runner` は `gh workflow run` の直後に `gh run watch "$run_id"` を呼ぶため、run を GitHub の API で参照できない間は `failed to get run: HTTP 404` で終わる。
[PR #121](https://github.com/shuhei1101/project-index/pull/121) の単体テストで発生し、手元の全件実行で再実行した。`run_runner` は [PR #116](https://github.com/shuhei1101/project-index/pull/116) で追加された。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

# 起動から GET /sources に応答するまでの時間（起動の後の全ての配信元の読み込み）を短くする

## 概要

dev-docs の画面のサーバーが、project-index を起動した直後でも `GET /sources` で配信元の一覧と状態を受け取れるようにする。

## 背景

[Issue #97](https://github.com/shuhei1101/project-index/issues/97) の要望。
[#85](https://github.com/shuhei1101/project-index/issues/85) の計測（状態のフォルダを空にして起動し、WSL の `/mnt/c` の下の配信元 14 件を配信）で、起動から待ち受けまでは 4 秒だったが、`GET /sources` に 2 秒以内に応答するまで 506.7 秒かかった。
[#94](https://github.com/shuhei1101/project-index/pull/94) は配信元ごとの最初の問い合わせを扱い、起動の後の全ての配信元の読み込みの時間をスコープ外としてこの Issue へ切り出した。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

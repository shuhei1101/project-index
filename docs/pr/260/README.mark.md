# 公開ドキュメントのページ名『読み取りAPI』を、書き込みの API も含む HTTP の API の一覧として見直す

## 概要

公開ドキュメントの読者が、ページ名から読み取り・端末の設定・書き込みの HTTP の API の一覧であることを読み取れるようにする。

## 背景

[Issue #257](https://github.com/shuhei1101/project-index/issues/257) の要望。
[PR #256](https://github.com/shuhei1101/project-index/pull/256)（起点 Issue [#252](https://github.com/shuhei1101/project-index/issues/252)）で書き込みの API `POST /sources/{source}/commits` を `docs/guide/読み取りAPI.md` の `## 書き込みの API` に加えたが、ページ名は『読み取りAPI』のまま。
#256 のドキュメント修正のレビューで提案され、#256 ではスコープ外にした。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |

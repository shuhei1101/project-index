# 文書のマーカーと prompt_doc が生成するマーカーを mdmark の JSON の記載へ移す

## 概要

このリポジトリの文書と `project-index prompt-doc` が生成する Markdown のマーカーを、mdmark v0.11.0 の JSON の記載へ移し、`mdmark check` が `legacy_mark` を出さないようにする。

## 背景

[Issue #64](https://github.com/shuhei1101/project-index/issues/64) の要望。
mdmark の [shuhei1101/mdmark#477](https://github.com/shuhei1101/mdmark/pull/477) でマーカーの設定を JSON のオブジェクトで記載できるようになり、今の書き方（`キー=値`・`+機能`・位置の値）は [shuhei1101/mdmark#479](https://github.com/shuhei1101/mdmark/issues/479) で参照する処理が削除される。
依頼元は [shuhei1101/mdmark#520](https://github.com/shuhei1101/mdmark/pull/520)（起点 Issue [shuhei1101/mdmark#478](https://github.com/shuhei1101/mdmark/issues/478)）。
着手の前提の mdmark v0.11.0 は [shuhei1101/mdmark#528](https://github.com/shuhei1101/mdmark/issues/528) でタグが打たれている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

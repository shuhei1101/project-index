# 設定の項目名以外に残る「控え」の文言を AI slop の単語の対応表に合わせて修正する

## 概要

設計書・ガイド・スキーマの例・コードのコメントと docstring・テストの docstring に残る「控え」の文言を、AI slop の単語の対応表の置き換え先に修正する。

## 背景

[Issue #67](https://github.com/shuhei1101/project-index/issues/67) の要望。
[PR #63](https://github.com/shuhei1101/project-index/pull/63) は `converters[].cache` の項目名と説明だけを修正し、同じ単語が他の記述に残っている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

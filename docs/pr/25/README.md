# dev-docs から移した処理の lint の既存の違反を解消し、ベースラインを除外する

## 概要

dev-docs から移した処理の ruff・pyright（strict）・complexipy の違反を、振る舞いを変えずに解消し、`# noqa`・`# pyright:` の指定・`complexipy-snapshot.json` を除外する。

## 背景

[Issue #17](https://github.com/shuhei1101/project-index/issues/17) の要望。
[#15](https://github.com/shuhei1101/project-index/pull/15) は、dev-docs から移した処理の既存の違反をベースラインに記載し、新しい違反だけを失敗にした。
dev-docs がこのリポジトリより緩い lint 設定で記載されていたためで、規約『設計原則』の「既存の Python のリポジトリは warn から始める」に従った。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |
| [プラグイン](./プラグイン.md) | プラグインの計画書 |

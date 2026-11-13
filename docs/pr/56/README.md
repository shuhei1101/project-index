# サーバーのスキーマの title・description の文言を AI slop の単語の対応表に合わせて修正する

## 概要

サーバーのスキーマ（`project-index.schema.yaml`・`settings.schema.yaml`）と、生成した `schemas/project-index.schema.json` の `title`・`description` の文言を、AI slop の単語の対応表の置き換え先に修正する。

## 背景

[Issue #40](https://github.com/shuhei1101/project-index/issues/40) の要望。
[shuhei1101/dev-docs#151](https://github.com/shuhei1101/dev-docs/issues/151) が依頼したスキーマの文言の修正のうち、[shuhei1101/dev-docs#163](https://github.com/shuhei1101/dev-docs/issues/163) で project-index へ移った分が残っている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

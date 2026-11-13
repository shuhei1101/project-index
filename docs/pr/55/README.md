# 配信元の設定に「使う場面」（when）を持たせ、describe と MCP の instructions で案内する

## 概要

エージェントが、配信元ごとに「どういう時にその配信元で探すか」（`when`）を、`describe` と文書の MCP の instructions で知れるようにする。

## 背景

[Issue #39](https://github.com/shuhei1101/project-index/issues/39) の要望（[shuhei1101/dev-docs#115](https://github.com/shuhei1101/dev-docs/issues/115) から移した Issue）。
配信元の設定は「何の文書か」を書く `description` だけを持ち、使う場面を書く項目が無い。
そのため、`describe(outside_scope: true)` が返す ID と `description` だけでは、作業範囲の外の配信元をいつ引けばよいかを判断できない。
決定は検討事項 D-152 の案 A（配信元の設定に `when` を追加する）。SessionStart での案内は [shuhei1101/dev-docs#92](https://github.com/shuhei1101/dev-docs/issues/92) で廃止したため対象外。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

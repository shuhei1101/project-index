# mdmark の参照を既定で develop の最新にし、設定でバージョンを固定できるようにする

## 概要

利用者が、mdmark の develop へ入った機能をタグを待たずに使用でき、必要なときは特定のバージョン（タグ・commit）に固定できるようにする。

## 背景

[Issue #88](https://github.com/shuhei1101/project-index/issues/88) の要望。
mdmark を固定のバージョンで参照していたため、mdmark の新規の機能を使用する作業 PR がタグを打つ Issue（[shuhei1101/mdmark#571](https://github.com/shuhei1101/mdmark/issues/571)）を待って止まった。
ユーザーの判断で、mdmark を参照する全てのリポジトリを develop の最新の参照へ切り替える。
mdmark の側は [shuhei1101/mdmark#620](https://github.com/shuhei1101/mdmark/issues/620)（[PR #621](https://github.com/shuhei1101/mdmark/pull/621)）で、`#develop`・`@develop` の参照で develop の最新の配布物を参照できるようになった。

project-index は、`write_docs` の Markdown の値の点検で `PATH` の mdmark の CLI を呼ぶ。
CLI の入れ方の案内（global-setup・ガイド）は既定のブランチの `npm install -g github:shuhei1101/mdmark`、外部ライブラリの設計書 [docs/library/LIB-7.yaml](https://github.com/shuhei1101/project-index/blob/e581544/docs/library/LIB-7.yaml) の参照は `@master` になっている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |
| [プラグイン](./プラグイン.md) | プラグインの計画書 |

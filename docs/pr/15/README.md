# dev-docs の文書の MCP・管理の MCP・配信元の読み込みとプラグインを移し、画面のサーバー向けの読み取り API と端末の設定の API を提供する

## 概要

dev-docs を入れずに project-index だけを入れた端末で、エージェントが文書の MCP を使用でき、dev-docs の画面のサーバーが project-index の読み取り API と端末の設定の API から配信元の文書・検索・リビジョン・端末の設定を取得できるようになる。

## 背景

[Issue #14](https://github.com/shuhei1101/project-index/issues/14) の要望。
[shuhei1101/dev-docs#114](https://github.com/shuhei1101/dev-docs/issues/114) で、文書とソースコードの索引・検索・書き込みの MCP と配信元の読み込みを dev-docs から project-index へ切り出し、dev-docs はそれを使用する画面のサーバーになると決まった。
project-index の develop には、立ち上げ（[#3](https://github.com/shuhei1101/project-index/pull/3)）で作った起動の入口・設計書の骨格・プラグインの定義だけがあり、移す機能のコードは無い。
dev-docs の作業 PR [shuhei1101/dev-docs#163](https://github.com/shuhei1101/dev-docs/pull/163) は、この作業 PR が提供する API を付け替え口とモックで呼ぶ前提で設計している（規約『複数リポジトリのAPI契約』）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |
| [プラグイン](./プラグイン.md) | プラグインの計画書 |

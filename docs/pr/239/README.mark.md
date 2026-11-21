# MCP サーバー・スキルの設計書を knowledge のテンプレートで作成し、実装を設計書に合わせる

## 概要

文書の MCP・管理の MCP とスキル global-setup・setup・feedback の設計書を knowledge のテンプレートで作成し、実装を設計書に合わせる。

## 背景

[Issue #238](https://github.com/shuhei1101/project-index/issues/238) の要望。
[shuhei1101/ai-monitor#3743](https://github.com/shuhei1101/ai-monitor/issues/3743)（作業 PR [shuhei1101/ai-monitor#3744](https://github.com/shuhei1101/ai-monitor/pull/3744)）で、AI Monitor の設計の工程に「エージェント・MCP サーバー設計」「エージェントフロー・LLM 呼び出し設計」が入った。
このリポジトリには MCP サーバー（instructions を含む）とスキルがあるが、knowledge のテンプレート（`template-mcp-server`・`template-agent-flow`）に沿った設計書が無く、配信元の設定にもその種類の行が無い。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 文書の MCP・管理の MCP の MCP サーバーの定義の計画書 |
| [プラグイン](./プラグイン.mark.md) | スキルのエージェントフローの計画書 |

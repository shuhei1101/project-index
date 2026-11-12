# PreToolUse のフックの出力に permissionDecision を付け、auto モードで書き換えた呼び出しが拒否されないようにする

## 概要

auto モードでも、PreToolUse のフックが入力を書き換えた文書の MCP のツールの呼び出しが拒否されないようにする。

## 背景

[Issue #38](https://github.com/shuhei1101/project-index/issues/38) の要望（shuhei1101/dev-docs#158 から移した Issue）。
`plugins/project-index/hooks/pre_tool_use.py` は `hookSpecificOutput` に `updatedInput` だけを返し、`permissionDecision` を返さない。
Claude Code の auto モードでは、`updatedInput` を `permissionDecision` なしで返すと、書き換えた呼び出しが拒否されうる（[公式の資料](https://code.claude.com/docs/en/hooks)）。
利用者の指示（TH-721）で、フックを持つプラグインは `permissionDecision` を付けると決まった。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [プラグイン](./プラグイン.md) | プラグインの計画書 |

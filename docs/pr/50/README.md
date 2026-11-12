# write_docs で worktree を省き cwd にワークツリーを指定すると TargetIsCloneError が返る不具合を修正する

## 概要

エージェントが `write_docs` に渡した `cwd` と、書き込む先のワークツリーの決まり方を、設計書・ツールの説明・実際の動作で一致させる。

## 背景

[Issue #47](https://github.com/shuhei1101/project-index/issues/47) の不具合（[#41](https://github.com/shuhei1101/project-index/pull/41) のスコープ外から切り出した Issue）。
`worktree` を省いて `cwd` に作業ブランチのワークツリーを指定した `write_docs` が、`TargetIsCloneError` を返した。
IF-6 は `worktree` の既定を「`cwd` がワークツリーの中ならそのワークツリー」とする。
一方で PreToolUse のフックは、エージェントが入れた `cwd` をセッションの作業場所で上書きするため（IF-20 の制約「上書き」）、指定した `cwd` は文書の MCP に届かない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [プラグイン](./プラグイン.md) | プラグインの計画書 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

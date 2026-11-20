# 常駐サーバーが何時間稼働しても、文書の MCP・管理の MCP が時間切れにならず応答するようにする

## 概要

エージェントが、常駐サーバーを何時間稼働させても、何本のセッションから呼んでも、文書の MCP と管理の MCP の応答を Claude Code の上限（60 秒）の内に受け取れるようにする。
劣化したときも管理の MCP の `restart` で起動し直せ、再発したときに原因を追える記録が残るようにする。

## 背景

[#197](https://github.com/shuhei1101/project-index/issues/197) の要望。
常駐サーバーは稼働から数時間（早いときは約 1.7 時間）で、プロセスが生きたまま応答が約 100 倍遅くなる（同じ worktree の読み込みが 4 秒から 203〜319 秒）。
文書の MCP と管理の MCP（`restart` を含む）が時間切れになり、kill して起動し直すまで全リポジトリのエージェントが設計書を読み書きできずに止まる（例: [shuhei1101/ai-monitor#3734](https://github.com/shuhei1101/ai-monitor/issues/3734)）。

負荷の高い間の時間切れは、[#82](https://github.com/shuhei1101/project-index/pull/82)（書き込みと worktree の読み取り）・[#147](https://github.com/shuhei1101/project-index/pull/147) と [#171](https://github.com/shuhei1101/project-index/pull/171)（起動の直後の文書の一覧）・[#216](https://github.com/shuhei1101/project-index/pull/216)（文書 1 件の取得）で経路ごとに修正してきた。
本件は #216 のマージの後も再発しており、稼働時間とともに全ての経路が遅くなる。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

# write_docs の項目のパスで `.` を含むマップのキーを指せるようにし、解決できない unset を見逃さないようにする

## 概要

エージェントが `write_docs` で、ファイル名のように `.` を含むマップのキーを項目のパスで指して改名・削除できるようにする。
解決できないパスを `unset` したときに、文書が変わらなかったことに気づけるようにする。

## 背景

[Issue #240](https://github.com/shuhei1101/project-index/issues/240) の要望（依頼元 [shuhei1101/ai-monitor#3738](https://github.com/shuhei1101/ai-monitor/issues/3738)）。
項目のパスは `.` を区切りにするため、`notes.mcp/server.py の補足` は `notes` → `mcp/server` → `py の補足` と読まれ、`unset` は項目が無いとして何もしないのに `status: updated`（`applied: true`）を返す。
`notes["mcp/server.py の補足"]` は記載方法の誤りで断られ、`replace` で文書全体を書き直すしか回避策が無い。
#162 は `#` で始まるパスの解決できない `unset` を違反にしたが、`#` で始まらないパスは今も何もしない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 項目のパスの解釈と `unset` の扱いの計画書 |

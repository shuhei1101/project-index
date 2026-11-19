---
name: feedback
description: 今の会話で利用者が AI に伝えた指摘（守ってほしいこと・単語の意味・経緯や判断の理由）を、rule-inject のルール・alias-inject の用語・project-index の文書として登録する。会話の後に、同じ指摘を次の会話で繰り返さずに済むようにしたいときに使用する
---

# feedback

質問は AskUserQuestion で、既定値を推奨の選択肢にして聞く。
- AskUserQuestion を使用できない環境では、番号つきの選択肢を文で示して回答を待つ

`write_docs` は文書の MCP（`mcp__plugin_project-index_project-index__write_docs`）にある。

## 手順

1. 文書の MCP の `search_docs` で、指摘を登録する手順のページを全文で取得する。
   - 引数: `source: "project-index"`・`outside_scope: true`・`filter`（`field: id`・`op: eq`・`values: ["docs/guide/会話の指摘を登録する.md"]`）・`view: "full"`
   - 文書の MCP につながらない（接続の失敗）ときは、`/project-index:global-setup` を案内して止まる
   - 該当 0 件か、配信元 `project-index` が無いエラー（`UnknownSourceError`）のときは、管理の MCP の `update` で project-index を更新するよう案内して止まる
2. 取得したページの手順を上から進める。
   - ページがリンクで指すほかのページ（『メタデータを付ける基準』など）は、同じ引数の `filter` の `values` を `docs/guide/{ページのファイル名}` にして取得する

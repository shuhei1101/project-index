---
name: setup
description: フォルダを project-index の配信元として端末の設定に登録する。2 回目以降は、範囲のファイルと管理用の YAML を突き合わせて追加・削除・改名を修正し、中身が変わったファイルのメタデータを見直す
argument-hint: "[path]"
---

# setup

`$ARGUMENTS` は配信元のフォルダ（以降 `{path}`）。省くと今の作業場所。

## 手順

1. 文書の MCP の `search_docs` で、配信元の登録の手順のページを全文で取得する。
   - 引数: `source: "project-index"`・`outside_scope: true`・`filter`（`field: id`・`op: eq`・`values: ["docs/guide/配信元を登録する.md"]`）・`view: "full"`
   - 文書の MCP につながらない（接続の失敗）ときは、`/project-index:global-setup` を案内して止まる
   - 該当 0 件か、配信元 `project-index` を配信していないエラーのときは、管理の MCP の `update` で project-index を更新するよう案内して止まる
2. 取得したページの手順を、`{path}` を配信元のフォルダにして上から進める。
   - ページがリンクで指すほかのページ（『メタデータを付ける基準』など）は、同じ引数の `filter` の `values` を `docs/guide/{ページのファイル名}` にして取得する

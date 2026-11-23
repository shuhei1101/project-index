---
name: setup
description: フォルダを project-index の配信元として端末の設定に登録し、2 回目以降は範囲のファイルと管理用の YAML を突き合わせて追加・削除・改名を修正し、中身が変わったファイルのメタデータを見直す
argument-hint: '[path]'
arguments:
- path
---

# フォルダを配信元として登録するスキル

## 引数

| 引数 | 説明 |
| --- | --- |
| `$path` | 配信元にするフォルダ。省くと今の作業場所 |

## 手順

### 配信元の登録の手順を取得する

文書の MCP で、配信元の登録の手順のページを全文で取得する（`filter` は `field: id`・`op: eq`・`values: ["docs/guide/配信元を登録する.md"]`）。
文書の MCP につながらない（接続の失敗）ときは、`/project-index:global-setup` を案内して止まる。
該当 0 件か、配信元 `project-index` が無いエラー（`UnknownSourceError`）のときは、管理の MCP の `update` で project-index を更新するよう案内して止まる。

呼ぶもの:

- ツール `mcp__plugin_project-index_project-index__search_docs` `{required: [source, outside_scope, filter, view], properties: {source: {const: project-index}, outside_scope: {const: true}, view: {const: full}}}`

### 手順を進める

取得したページの手順を、`$path` を配信元のフォルダにして上から進める。
ページがリンクで指すほかのページ（『メタデータを付ける基準』など）は、同じ引数の `filter` の `values` を `docs/guide/{ページのファイル名}` にして取得する。
質問は AskUserQuestion で、既定値を推奨の選択肢にして聞く。
管理の MCP のツール（`check_project`・`reload`）は `mcp__plugin_project-index_project-index-admin__` で始まる名前、`write_docs` は `mcp__plugin_project-index_project-index__write_docs` で呼ぶ。

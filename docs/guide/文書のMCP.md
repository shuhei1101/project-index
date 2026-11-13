# 文書のMCP

7 つのツールの引数・既定値・上限・エラーの一覧

## 共通

接続先は `http://127.0.0.1:${PROJECT_INDEX_PORT:-8786}/mcp` の 1 つで、トランスポートは HTTP（Streamable HTTP）です。
ツールは全配信元で共通で、配信元は引数 `source` で指します。

<!-- table: data -->

| ツール | 種類 | 役割 |
| --- | --- | --- |
| `search_docs` | 読み取り | 検索・取得・一覧・件数・集計 |
| `write_docs` | 書き込み | 作成・部分更新・置き換え（一括） |
| `delete_docs` | 書き込み（`destructiveHint: true`） | 削除（一括） |
| `describe` | 読み取り | 使える配信元の一覧・説明書・種類・スキーマ |
| `list_changes` | 読み取り | 区間か前回読んだ時点からの変更 |
| `trace_related` | 読み取り | 関連のたどりと関連の候補 |
| `list_match_words` | 読み取り | 用語の照合に使う語の一覧 |

<!-- /table -->

読み取りのツールには `readOnlyHint: true` が付き、並列に呼ばれます。
引数の検証は strict tool use を使わず、サーバーが配信元のスキーマで検証し、直し方を添えてエラーを返します。
`initialize` の `instructions` は、`search_docs`・`trace_related`・`list_changes`・`write_docs` を使う場面と、grep・Read が向く場面（コードの識別子・文字列の出現箇所、配信の範囲の外のファイル）、`describe(source)` で種類と書き方を確かめてから探す・書く順序、タグの付け方（[使われているタグを引く](#使われているタグを引く)）を持ち、4,096 字以内です。
`instructions` とツールごとの description は、起動のときに `content/prompts/mcp/` のプロンプトの YAML から読みます（置き場所は環境変数 `PROJECT_INDEX_PROMPTS_DIR` で変えられます）。
YAML を書き換えたときは、再起動で反映します。

### 共通の引数

<!-- table: data -->

| 引数 | 型 | 説明 | 補足 |
| --- | --- | --- | --- |
| `source` | str（`search_docs`・`list_changes` は list[str] も可） | 配信元の ID（端末の設定の `sources[].id`） | 省略すると作業中の配信元。`scope` に当たらない配信元はエラー（`outside_scope` を除く）。`search_docs`・`list_changes` は配列か `*`（読める全配信元）も受ける |
| `ref` | str | 読むリビジョン（ブランチ・コミット・タグ） | 省略すると配信元の `default_ref`。作業中の配信元は作業ツリー。Git 管理外の配信元と、複数の配信元を指したときは渡せない |
| `worktree` | str | 読み書きするワークツリーのパス | 配信元の `worktrees` に当たるパスだけ。省略して `cwd` がワークツリーの中なら、そのワークツリー |
| `format` | `markdown` / `json` | 返す形式 | 既定 `markdown` |
| `cwd` | str | 作業場所 | プラグインのフックが入れる。エージェントは指定しない |
| `session_id`・`agent_id` | str | 会話キー | 同じ。メインの会話は `agent_id` が空 |
| `outside_scope` | bool | `true` のとき、`cwd` が `scope` に当たらない配信元も、端末の設定の `sources[].outside_read` が真なら作業範囲の外（参考）として読む | 既定 `false`。`describe`・`search_docs`・`trace_related`・`list_changes` だけが持ち、作業範囲の外を読むのは `source` に ID を 1 つ渡したときだけ（配列・`*` は `scope` に当たる配信元だけを対象にする）。`describe` は `source` を省くと、作業範囲の外で読める配信元の一覧を加える。下の「作業範囲の外」 |

<!-- /table -->

ツールの引数に無いキーは無視します。
`ref` を持つのは `search_docs` と `trace_related` で、`write_docs`・`delete_docs` は `ref` を持ちません。
`write_docs`・`delete_docs` は `format` によらず JSON を返します。

### 作業範囲の外

`outside_scope: true` で作業範囲の外の配信元を読んだ結果は、「作業範囲の外（参考）」の表示を付けて返します。
`markdown` は先頭の行にこの表示を出し、`search_docs` の `view: full` の `<document>` に `outside_scope="true"` を付けます。
`json` は `outside_scope: true` を返します。
外から読んだ呼び出しは、作業場所（`cwd`）と配信元の ID を要求のログに残します。
引数なしの `describe()` の一覧には、作業範囲の外の配信元を載せません。
作業範囲の外で読める配信元の ID は、`source` を省いた `describe(outside_scope: true)` で引けます。

### 返す形式

| ツールの種類 | `markdown`（既定） | `json` |
| --- | --- | --- |
| 一覧・件数・集計 | Markdown の表。先頭に総件数 | 行の配列と総件数などを持つオブジェクト |
| 本文 | YAML が正本の文書は YAML のまま、Markdown の文書は Markdown。複数なら `<document>` で包む。包みに文書ごとの `path`・`scope` を付ける | 文書のオブジェクトの配列。各項目に `path`・`scope` |
| 差分 | git と同じ `+`・`-` の行。`view: full` は文書ごとに `<document>` で包み、`path`・`scope` を付ける | 変わったキーと前後の値。各項目に `path`・`scope` |
| 書き込み・削除 | JSON | JSON |

`markdown` のときは structuredContent を返しません。
`json` のときと書き込み・削除は、structuredContent と text に同じ JSON を入れます。

### 文書の場所と範囲

`search_docs`・`trace_related`・`list_changes` は、返した文書ごとに場所（`path`）と返した範囲（`scope`）を載せます。
`markdown` は `<document path="..." scope="...">` の属性、`json` は各項目の直下（`id`・`source` と同じ階層で `values` の外）の `path`・`scope` です。
rule-inject は、この `path` と `scope` で文書を既読にします。

`path` は、配信元（ワークツリーを指したときはワークツリー）の直下と文書のパスを結んだ絶対パスです。
`body_file` のある `records` の要素は、`body_file` が指すファイルのパスになります。
メタデータのキー `path`（`values` の中。管理用の YAML では `files[].path` の値）とは別の項目です。

<!-- table: data -->

| `scope` | 返したもの | 該当する呼び出し |
| --- | --- | --- |
| `full` | 本文を切らずに返した | `search_docs` の `view: full` で、`max_chars_per_field` に収まり、`snippets` を渡さなかったとき |
| `section` | 本文の一部を返した | `max_chars_per_field` で切った本文、`snippets`、`sections`・`lines` で切り出した本文、`body_file` の無い `records` の要素、`list_changes` の `view: full` の差分 |
| `summary` | 本文を返さなかった | `view: summary`、`exclude_fields` で `body` を除いた `view: full`、`trace_related`、`list_changes` の `view: summary` |

<!-- /table -->

次の文書には `path`・`scope` を載せません。
`markdown` の `<document>` は属性の無い包みになり、`json` の項目は `path`・`scope` を持ちません。

- `ref` を渡して読んだ文書
- `list_changes` で `to` を渡したときの文書、`change` が `deleted` の文書
- 返し済みにした文書
- `view: ids`・`view: count` の結果と、読めない配信元の文書

### 1 セッション 1 回

サーバーは会話キー（`session_id`・`agent_id`）ごとに、返した文書の id とハッシュを記録します。
同じバージョンの本文と、`trace_related` の関連の相手の名前・概要文は、2 回目から `（この会話で返し済み）` だけを返します。
`repeat_seen: true` で取り直せます。
一覧の各行の概要文は、選ぶために使うので省きません。

`search_docs` の `sections`・`lines` を渡した呼び出しは、返した文書を記録せず、返し済みの文書でも切り出した本文を返します。
`list_changes` の前回読んだ時点も、この呼び出しでは進みません。

### 作成日時・更新日時

メタデータの `created`・`updated` は次の順で決めます。

1. Git の履歴があれば、そのファイルの最初と最後のコミットの日時
2. 無ければ、文書のメタデータの `created`・`updated`。Git 管理外の配信元では `write_docs` が付ける
3. どちらも無ければ空。並べ替えでは末尾

### バージョン

文書の `version` は内容のハッシュ（短縮）です。
ファイルの更新日時か大きさが変わった文書は、次の呼び出しで読み直します。
`write_docs`・`delete_docs` の `expected_version` に、読んだときの `version` を渡します。

## search_docs

条件に当たる文書を、指定した項目・量・順で返します。
ID で絞れば取得、`view: summary` で一覧、`view: count` で件数、`group_by` で集計になります。

<!-- table: data -->

| 引数 | 型 | 既定 | 説明 |
| --- | --- | --- | --- |
| `filter` | Group か Condition | 全件 | 条件の木。下の「条件」 |
| `view` | `ids` / `summary` / `full` / `count` | `summary` | `ids` は ID だけ、`summary` は共通のメタデータ、`full` は本文込み、`count` は件数だけ |
| `fields` | list[str] | `view` に従う | 返す項目に加える項目（`body`・種類ごとの項目・計算項目も可。`@matches` は文書ごとに本文の条件に当たった行の数を返す） |
| `exclude_fields` | list[str] | なし | 返す項目から除く項目 |
| `order_by` | list[{`field`, `direction`}] | `id` の昇順 | 複数キーの並べ替え。先のキーが優先。`direction` は `asc` / `desc`。日時が空の文書は末尾。`@chars` で文字数順、`@matches` でよく当たる順 |
| `group_by` | str | なし | 指定した項目の値ごとの件数を返す。配列の項目は要素ごとに数える。値は条件の比較と同じく正規化（NFKC と `casefold`）してから数え、表記だけが違う値（`MCP`・`ｍｃｐ`・`mcp`）は 1 つにまとめる。1 つの文書に付いた同じ値は 1 件と数える。まとめた値は、付いている文書が最も多い表記（同数なら値の昇順で先のもの）で返す |
| `limit` | int | 20 | 返す件数。最大 100 で、超えたら 100 に丸めて `notes` で知らせる |
| `cursor` | str | なし | 前回の `next_cursor`。ほかの引数は前回と同じにする |
| `skip` | int | 0 | 先頭から飛ばす件数 |
| `max_chars` | int | 20,000 | 結果全体の文字数の上限。上限は 40,000 |
| `max_chars_per_field` | int | 2,000（`view: full` は 10,000） | 長い値を末尾で切り、残りの文字数を添える |
| `snippets` | {`context_lines`, `before`, `after`, `max_per_doc`} | なし | 本文の代わりに、条件に当たった行と前後の行だけを行番号つきで返す。下の「抜粋」 |
| `sections` | list[str] | なし（本文の全文） | Markdown の本文から返すセクションの見出し。`view: full` のときだけで、`lines` と同時に渡せない。下の「本文の一部」 |
| `lines` | {`offset`, `limit`} | なし（本文の全文） | 本文から返す行の範囲。`view: full` のときだけで、`sections` と同時に渡せない。文書の種類を問わない。下の「本文の一部」 |
| `repeat_seen` | bool | `false` | この会話で返し済みの本文も返す |
| `term` | str | なし（用語で絞らない） | 用語。`alias_type` を持つ documents の行の文書のうち、`name` か `aliases` の値がこの語に一致する文書に当たる。条件の比較と同じ正規化（NFKC と `casefold`）をして完全一致で比べ、部分一致はしない。`filter` と同時に渡すと両方に当たる文書を返す。`alias_type` を持つ行が無い配信元では 0 件で、`notes` で知らせる |

<!-- /table -->

### 条件

```text
Group     = {"and": [Group | Condition, ...]} | {"or": [Group | Condition, ...]} | {"not": Group | Condition}
Condition = {"field": str, "op": enum, "values": [str, ...], "match": "any" | "all", "case_sensitive": bool}
```

<!-- table: data -->

| 項目 | 説明 |
| --- | --- |
| 入れ子 | 深さの制限は無い |
| `not` | 中の条件か束に当たらない文書に当たる。`and`・`or` の中にも置ける。束は `and`・`or`・`not` のどれか 1 つのキーだけを持つ。`not` の中の `body`・`*` の条件は、`@matches` と抜粋の判定に使わない |
| `field` | メタデータのキー（`id`・`kind`・`name`・`tags`・`main_tags`・`updated` など）、種類ごとの項目、`body`（本文）、`*`（全項目）、計算項目（`@chars` 文字数・`@path` ファイルのパス・`@sections` セクションの一覧）。`@matches` は `fields`・`order_by` でだけ使え、条件には使えない |
| `op` | `eq`・`ne`・`prefix`・`suffix`・`contains`・`not_contains`・`regex`・`glob`・`gt`・`gte`・`lt`・`lte`・`exists`・`not_exists`。`regex` は値の各行に当たる（`^`・`$` は各行の先頭・末尾。値全体の先頭・末尾は `\A`・`\Z`）。パターンには正規化をかけず、`case_sensitive: false` は `re.IGNORECASE` と NFKC にした値で比べる。`glob` は値全体に当て、`**` は `/` をまたぎ、`*`・`?` は `/` をまたがない。`@path` を含む文字列の項目で使える |
| `values` | 文字列の配列。数値・日付は項目の型で解釈し、日付は `today`・`-7d` も受ける。`exists`・`not_exists` だけ省ける |
| `match` | `values` の複数を OR（`any`、既定）か AND（`all`）で比べる |
| `case_sensitive` | 既定 `false`。大文字小文字と全角半角（NFKC）を区別しない |

<!-- /table -->

### レスポンス

<!-- table: data -->

| フィールド | 説明 |
| --- | --- |
| `total_count` | 条件に当たった総件数。複数の配信元では配信元ごとにも返す |
| `returned` | 返した件数 |
| `next_cursor` | 続きがあるときだけ |
| `truncated` | `max_chars` で打ち切ったか |
| `notes` | 丸めた・打ち切った・読めなかったファイルの知らせと次の手 |
| `groups` | `group_by` のときの値ごとの件数 |
| `outside_scope` | 作業範囲の外から読んだか。[作業範囲の外](#作業範囲の外)のとおり |
| `items[]` | 文書。ID で絞ったときは指定した順。各文書に `id`・`version`、`view: full` で `body`。複数の配信元を指したときは `source` が付く |
| `items[].path`・`items[].scope` | 文書の場所と返した範囲。[文書の場所と範囲](#文書の場所と範囲)のとおり。`view: ids`・`count` では持たない |
| `items[].snippets` | `snippets` を渡したときの抜粋。下の「抜粋」 |
| `items[].values.@matches` | `fields` に `@matches` を渡したときの、本文の条件に当たった本文の行の数。下の「当たった数」 |
| `items[].ranges` | `sections`・`lines` を渡したときの、切り出した本文の行の範囲（`start_line`・`end_line`。本文の行番号、1 始まり）の配列。切り出す範囲が無ければ空 |
| `items[].total_lines` | `sections`・`lines` を渡したときの、本文の全体の行数 |

<!-- /table -->

YAML として読めないファイルがあっても、そのファイルを除いて返し、`notes` で知らせます。
種類のスキーマの `$ref` を解決できない文書は結果に含め、解決できなかった `$ref` とスキーマのファイルのパスを `notes` で知らせます。

### 使われているタグを引く

タグは自由な文字列で、配信元はタグのマスターを持ちません。
使われているタグは `group_by: tags` で件数つきで引けます。
配信元をまたいで引くときは `source: "*"` を渡します。

タグの付け方と、タグを `{name, main}` のオブジェクトの配列で持つ種類の読み方は [文書のメタデータ](./コアコンセプト-文書のメタデータ.md) にあります。

### 抜粋

`snippets` は、条件の `body`・`*` の `eq`・`prefix`・`suffix`・`contains`・`regex` と同じ判定で本文の行ごとに当たった行を探し、前後の行と合わせて返します。
`eq`・`prefix`・`suffix` は行の部分一致で探し、`case_sensitive` は条件と同じです。

| キー | 既定 | 説明 |
| --- | --- | --- |
| `context_lines` | 1 | `before`・`after` を省いたときの前と後ろの行の数 |
| `before` | `context_lines` | 当たった行の前に返す行の数 |
| `after` | `context_lines` | 当たった行の後ろに返す行の数 |
| `max_per_doc` | 3 | 文書ごとに返す抜粋の数。重なる範囲は 1 つにまとめる |

`markdown` は grep の `-n` と同じく、当たった行を `{行番号}:{行}`、前後の行を `{行番号}-{行}` で出し、抜粋の間に `--` を置きます。
`json` は `items[].snippets[].lines[]` の各行に `line`（1 始まりの行番号）・`text`・`hit`（当たった行か）を持ちます。

### 当たった数

`@matches` は、`filter` の `body`・`*` の条件（`not` の下を除く）のどれかに当たった本文の全文の行を数えます。
行の判定は抜粋と同じで、本文の条件が無ければ 0 です。
`fields` で返し、`order_by: [{"field": "@matches", "direction": "desc"}]` でよく当たる順に並べます。
`sections`・`lines` を渡しても、数えるのは本文の全文の行です。

### 本文の一部

`sections`・`lines` は、`view: full` の本文の一部だけを返します。
どちらも返した文書の `scope` は `section` で、返し済みの記録をしません。

| 引数 | 説明 |
| --- | --- |
| `sections` | Markdown の本文から返すセクションの見出しの文字列。見出しの行から、次の同じか上の階層の見出しの前の行までを返す。見出しは `#` と前後の空白を除いた文字列と完全一致で当て、当たる見出しが複数あれば全て返す。YAML の文書と、当たる見出しの無い文書は本文を空で返し、`notes` で知らせる |
| `lines.offset` | 返す最初の行の行番号（1 始まり）。既定 1。1 以上 |
| `lines.limit` | 返す行の数。既定は本文の末尾まで。1 以上 |

`view: full` 以外で渡す、`sections` と `lines` を同時に渡す、`lines` の `offset`・`limit` が 1 未満のときは、`InvalidArgumentError` です。

切り出した範囲は `items[].ranges`、本文の全体の行数は `items[].total_lines` で返します。
`markdown` は `<document>` の前の行に `{id}: {start_line}-{end_line} 行目 / 全 {total_lines} 行` を出します（範囲が複数なら `・` で並べます）。

次の順に当てます。

1. `sections`・`lines` で本文を切り出す
2. 切り出した範囲の中で `snippets` の抜粋を探す
3. `max_chars_per_field` で切る

抜粋の行番号は本文の行番号のままで、そのまま `lines` に渡せます。

## write_docs

文書の作成・部分更新・置き換えを配列で受け、変更を当てた後の文書を配信元のスキーマと `validators[]` に通してから書き込みます。
書き込みの先は [配信元と権限](./コアコンセプト-配信元と権限.md) の「書き込みの先」のとおりです。

| 引数 | 型 | 既定 | 説明 |
| --- | --- | --- | --- |
| `operations` | list[Operation] | 必須 | 並べた順に当てる操作。1 回に 50 件まで |
| `atomic` | bool | `true` | `true` は 1 件でも失敗したら何も書かない。`false` は成功分を書き、失敗分を添字付きで返す |
| `dry_run` | bool | `false` | 本番と同じ検証・バージョンの確認・差分を返し、書き込まない |

<!-- table: data -->

| Operation のキー | 使える `op` | 説明 |
| --- | --- | --- |
| `op` | すべて | `create`（新しい文書）・`update`（部分更新）・`replace`（全項目の置き換え）。upsert は無い |
| `kind` | `create`（必須） | 種類（`documents[].id`）。スキーマと置き場所を決める |
| `id` | `update`・`replace`（必須）、`create`（省略可） | 対象の文書の ID。`create` で省くと `ids.format` から作る |
| `expected_version` | `update`・`replace`（必須） | 読んだときのバージョン。`update` では項目のパスごとのハッシュも受ける |
| `data` | `create`・`replace`（必須） | 文書の全項目 |
| `set` | `update` | 項目に値を入れる。オブジェクトは再帰的にマージし、配列と値は置き換える |
| `unset` | `update` | 消す項目のパスの配列 |
| `add_to` | `update` | 配列の項目の末尾へ要素を追加する |
| `remove_from` | `update` | 配列の項目から一致する要素を削除する |
| `text_edits` | `update` | `[{field, old, new, replace_all}]`。`replace_all` が `false` のとき `old` が 1 か所だけ一致すること |

<!-- /table -->

`data`・`set`・`add_to`・`remove_from` のキーと、`unset`・`text_edits[].field` の項目のパスの先頭のキーは、種類の行の `metadata` に書いた共通のキー（`name` など）なら、対応する列名（入れ子は `.` でつないだパス）に読み替えてから当てます。
列名をそのまま渡したキーと、`metadata` に書いていないキーは読み替えません。
共通のキーとその列名を同じ操作に両方渡すと、`InvalidArgumentError` です。
種類ごとの対応は `describe(source, kind)` で引けます。

行の `metadata` が `tags: tags[].name` のとき、`tags` への操作はオブジェクトの配列へ書き戻し、元の要素の `main` などのキーを保ちます。

| 操作 | `tags` | `main_tags`（`tags[main].name`） |
| --- | --- | --- |
| `add_to` | `{name: x}` の要素を末尾に追加する（`main` を付けない） | 渡した名前の要素に `main: true` を付ける |
| `remove_from` | `name` が一致する要素を削除する | 渡した名前の要素の `main` を削除する。無い名前は何もしない |
| `set` | 渡した名前の並びで置き換える。元からあった名前の要素は他のキーを保つ | 渡した名前の要素の `main` を `true`、それ以外の要素の `main` を削除する |
| `unset` | - | 全ての要素の `main` を削除する |

`main_tags` の `set`・`add_to` に `tags` に無い名前を渡すと、`InvalidArgumentError` です。

全ての操作を当ててから 1 回だけ検証し、通ったときだけ一時ファイルに書いてから置き換えます。
読み込み・検査・書き込みは配信元ごとの排他ロックの中で行い、書いた後に `generators[]` を流します。

種類のスキーマで `contentMediaType: text/markdown` を持つキーは Markdown のキーで、操作で値を変えたキー（`create` は値を持つ全てのキー）を mdmark の点検（`mdmark check --text -`）に通します。
点検のずれのうち描画時の書き方の警告（`diagram_invalid`・`syntax_warning`）は、項目のパス・`mdmark の {種類}（{行} 行目）`・mdmark の内容の違反になり、スキーマの違反と同じく書き込みを止めます。
ほかの種類（知らない印の `unknown_mark`・図の配置のずれ・見つからないファイル）では書き込みを止めません。
mdmark の CLI が `PATH` に無いか、点検が端末の設定の `script_timeout_sec` を超えた・結果を出さずに終わったときは、点検せずに書き込み、そのキーと理由を `results[].unchecked` に返します。

レスポンスは `applied`（1 件以上を書いたか。`dry_run` は常に `false`）と `results[]` です。
`results[]` は `index`・`id`・`status`（`created`・`updated`・`replaced`・`failed`）・`version`・`diff`（`updated`・`replaced` と `dry_run`）・`errors`（`failed` のとき、項目のパス・決まり・直し方と、スキーマの違反では違反した項目のスキーマの `title`・`description`・`x-rules`・`examples`・`x-bad-examples` のうちスキーマが持つものを入れた `schema`）・`unchecked`（mdmark で点検できなかったキーのパスと理由）を持ちます。

## delete_docs

文書を配列で受けて物理削除します。
Git の配信元で消した文書は Git で戻せます。

| 引数 | 型 | 既定 | 説明 |
| --- | --- | --- | --- |
| `targets` | list[{`id`, `expected_version`}] | 必須 | 消す文書と読んだときのバージョン。1 回に 50 件まで |
| `on_referenced` | `fail` / `unlink` | `fail` | 他の文書の `related` から参照されているとき。`unlink` は参照も外して消す |
| `atomic`・`dry_run` | bool | `true`・`false` | `write_docs` と同じ |

レスポンスは `applied` と `results[]`（`status` は `deleted`・`failed`）、`on_referenced: unlink` のときの `unlinked[]`（参照を外した文書の `id`・`version`）です。
Git 管理外の配信元では、種類の `documents[].writable` が削除を許していることが要ります。

## describe

引数の数で返すものが変わります。

| 引数 | 返すもの |
| --- | --- |
| なし | 今の作業場所から使える配信元の一覧（`id`・権限 `read` / `write`・作業中か・`description`）と、作業場所、使える配信元の警告（`warnings[]`） |
| `outside_scope: true`（`source` なし） | 引数なしと同じ一覧に加えて、作業範囲の外（参考）で読める配信元（`scope` に当たらず `sources[].outside_read` が真）の一覧（`outside_sources[]` の `id`・`description`） |
| `source` | その配信元の説明書（`instructions`）と種類（`kinds[]`）の一覧。Git の配信元は、ブランチ・タグ（`refs.branches[]`・`refs.tags[]`）と、`worktrees` に当たるワークツリー（`worktrees[]` の `path`・`branch`）の一覧も返す |
| `source`・`kind` | その種類の共通のキーと列名の対応（`metadata`）と、スキーマ（YAML のまま） |

`warnings[]` は、使える配信元の同期のずれ（metadata の列の欠け・管理用の YAML に無いファイル・ファイルが無い行・どの文書にも当たらない関連）・エイリアスのキーの違反・どの文書にも当たらない `nav` の条件、配信元と端末の設定のバージョンが古いこと、検証で外した配信元、端末の設定の最上位の知らないキー（端末の設定のファイルとキーのパスを 1 件にまとめる）です。
`markdown` では配信元の表の後に「注意」の見出しの下に 1 行ずつ出し、0 件のときは見出しごと出しません。
使える配信元が無い作業場所では、表の代わりに `/project-index:setup` で配信元にできることを返し、端末の設定のバージョン・端末の設定の最上位の知らないキーと検証で外した配信元の警告は載せます。
詳しい内容は管理の MCP の `check_project` で確認します。

`metadata` は、種類の行の `metadata` をそのまま返します。
`markdown` ではスキーマの前に「共通のキー | 列名」の表で出し、`json` では `metadata` に `{name: title}` の形で入れます。
対応を持たない種類では、表を出さず、`json` の `metadata` は空です。
書いていないキーは、同じ名前の列を読みます。

ワークツリーの `path` は絶対パスで、そのまま `search_docs` などの `worktree` に渡せます。
`branch` は checkout しているブランチで、detached HEAD のときは `null` です。

説明書には配信元に固有のことだけが記載されます。
タグの一覧・文書の件数は `search_docs` の `group_by`・`view: count` で取ります。

## list_match_words

配信元の `alias_type` を持つ行の文書から、用語の照合に使う語（`name` と `aliases`）を、指す文書の ID とともに返します。

| 引数 | 型 | 既定 | 説明 |
| --- | --- | --- | --- |
| `source` | str | 必須 | 配信元の ID |

ほかに共通の引数 `worktree`・`format`・`cwd` を持ちます。
レスポンスは `words[]`（`word`・語が指す文書の `id`・`kind` の `name` / `alias`）です。
エイリアスのキーが alias-inject のスキーマに通らない文書の語は載せません。
`search_docs` の `term` と同じ文書から集め、件数の上限はありません。
`alias_type` を持つ行が無い配信元は、空の一覧を返します。

## list_changes

区間か、この会話で前回読んだ時点から今までに変わった文書・変わったキー・差分の行を返します。

<!-- table: data -->

| 引数 | 型 | 既定 | 説明 |
| --- | --- | --- | --- |
| `from` | str | この会話で前回読んだ時点 | 区間の始点（commit・日時・ブランチ・タグ）。日時はその時点の最後の commit に解決する。Git 管理外の配信元では渡せない |
| `to` | str | 今の作業ツリー | 区間の終点。`from` を渡したときだけ |
| `filter` | Group か Condition | 全件 | `search_docs` と同じ条件で、対象の文書を絞る |
| `contains` | {`value`, `regex`, `case_sensitive`} | なし | 語の出現数が変わった文書だけを返し、語が入った・消えた区間を添える。`filter` と同時に渡すと両方に当たる文書を返す。下の「語の当て方」 |
| `view` | `summary` / `full` | `summary` | `summary` は変わった文書と変わったキー、`full` は差分の行まで |
| `limit` | int | 20 | 返す文書の数。最大 100 |
| `cursor` | str | なし | 前回の `next_cursor` |
| `max_chars` | int | 20,000 | 結果全体の文字数の上限。上限は 40,000 |

<!-- /table -->

レスポンスは、解決した始点・終点（`range.from`・`range.to` の入力値・commit・日時）、`total_count`、`items[]`（`id`・`change` の `added` / `modified` / `deleted` / `unchanged`・`keys`・`view: full` の `diff`・今の作業ツリーが終点のときの `path`・`scope`・`contains` を渡したときの `contains_changes`）、`truncated`、`notes` です。
`change: unchanged` は、`contains` を渡して、区間の中で語が入って消え、両端の内容が同じ文書だけが持ちます。
前回読んだ時点は、`search_docs` が `state_dir` に記録した、文書ごとの最後に返した内容と比べます。

### 語の当て方

`contains` は `value`（探す語か正規表現。空文字は渡せない）、`regex`（`value` を正規表現として当てるか。既定 `false`）、`case_sensitive`（大文字小文字と全角半角を区別するか。既定 `false`。`search_docs` の条件と同じ）を持ちます。

区間の中の commit（`git log {from}..{to}` が並べる commit のうち、親が 2 つ以上のマージ commit を除く）ごとに、その commit と親の文書の内容で語の出現数（正規表現なら当たった数）を比べ、数が変わった commit を返します。
`git log -S`（正規表現は `--pickaxe-regex`）と同じ当て方です。
語を含む行を書き換えただけで出現数が同じ commit と、マージの競合の解消で入った語は返しません。
`to` を省いた呼び出しは、`{from}..HEAD` の commit に加えて、HEAD と今の作業ツリーを最後の区間として比べます。
文書の内容は `search_docs` の `view: full` が返す本文で、`records` の文書も 1 件ずつ比べます。

文書ごとの `items[].contains_changes` に、出現数が増えた（`added`）・減った（`removed`）区間を古い順に並べます。

| キー | 説明 |
| --- | --- |
| `kind` | `added` / `removed` |
| `from`・`to` | 区間の両端の `commit` と `date`。`to` を省いた呼び出しの HEAD と作業ツリーの区間は、`to` が `range.to` と同じ `作業ツリー`（commit を持たない） |
| `count_before`・`count_after` | 区間の前後の語の出現数 |

`from` を省いて前回読んだ時点と比べた呼び出しは、比べた区間全体の 1 要素を返し、`from`・`to` は `range` と同じ値です。

## trace_related

起点の文書かコードのパスから `related` をたどって、関連する文書を返します。

<!-- table: data -->

| 引数 | 型 | 既定 | 説明 |
| --- | --- | --- | --- |
| `from_ids` | list[str] | なし | 起点の文書の ID。`code_paths` とどちらか 1 つを渡す |
| `code_paths` | list[str] | なし | 起点のコードのパス（配信元の直下から）。`records`・`body_file` の行で、そのパスを本文に持つ文書を起点にする |
| `depth` | int | 2 | たどる深さ。1〜4 で、超えたら 4 に丸めて `notes` で知らせる |
| `direction` | `out` / `in` / `both` | `both` | `out` は起点の `related` が指す先、`in` は起点を `related` で指す文書 |
| `suggest` | bool | `false` | `true` で、関連の候補（同じ commit での変更・同じ会話での編集と閲覧）を上位 3 件返す |
| `repeat_seen` | bool | `false` | この会話で返し済みの相手の名前・概要文も返す |

<!-- /table -->

一度たどった文書はたどりません。
`json` の各項目は、たどった文書の `path` と `scope: summary` を持ちます。
候補は `related` に書き込まないので、採用するときは `write_docs` で `related` に追加します。
たどった先が読めない配信元の文書は、ID だけを返します。

設計書を起点に `direction: in` で呼ぶと、結果の `via.type` が `implements` の文書が、その設計書を実装するコードです。
コードを起点に `direction: in` で呼ぶと、`via.type` が `tests` の文書が、そのコードのテストです。

## エラー

エラーは `isError: true` のツール結果で返し、本文に原因と次の手を記載します。

<!-- table: data -->

| エラー | 発生条件 | 本文に記載すること |
| --- | --- | --- |
| SourceNotReadableError | `cwd` が配信元の `scope.read`・`scope.write` に当たらない（`outside_scope: true` のときは、加えて `outside_read` が偽）、または `cwd` が無い | 今の作業場所から使える配信元の一覧。`outside_read` が真で `outside_scope` を渡していないときは、`outside_scope: true` で作業範囲の外を参考に読めること |
| SourceNotWritableError | `cwd` が配信元の `scope.write` に当たらない | 今の作業場所から使える配信元の一覧 |
| SourceNotServedError | 起動時の検証で外したか `enabled: false` の配信元を指した | 違反したキーのパスと理由 |
| WorktreeNotMatchedError | `worktree` が配信元の `worktrees` に当たらない | 渡したパスと `worktrees` の値 |
| TargetIsCloneError | Git の配信元で、書く先がクローン本体になる | `worktree` でワークツリーを指すこと |
| InvalidArgumentError | `filter`・`order_by`・`group_by`・Operation の中の知らない項目・型の合わない値、50 件を超える操作、必須のキーの欠け、`text_edits` の `old` が 1 か所に一致しない、`ref` を渡せない配信元に `ref`・`from`・`to` を渡した、`create` の置き場所のファイル名が `documents[].exclude[]` に当たる、共通のキーとその列名を同じ操作に両方渡した、束が `and`・`or`・`not` のキーを 2 つ以上持つ、`@matches` を条件に使った、`sections` と `lines` を同時に渡した、`view: full` 以外で `sections`・`lines` を渡した、`lines` の `offset`・`limit` が 1 未満、`contains.value` が空、`contains.regex: true` で `value` が正規表現として読めない、`main_tags` の `set`・`add_to` に `tags` に無い名前を渡した | 項目のパス・期待する型・実際の値と、`describe(source, kind)` でスキーマを見ること |
| RefNotFoundError | `ref`・`from`・`to` を commit に解決できない | 解決できなかった値 |
| UnknownKindError | `kind` が配信元の種類に無い | その配信元の種類の一覧 |
| DocumentNotFoundError | 指した ID の文書が無い | 見つからなかった ID と、近い ID の候補 |
| VersionMismatchError | `expected_version` が今のバージョンと違う | 今のバージョンと差分、読み直して呼び直すこと |
| ValidationFailedError | 変更を当てた後の文書がスキーマか `validators[]` に通らない、または種類のスキーマの `$ref` を解決できない（`atomic: true`） | 違反ごとの添字・パス・決まり・直し方。スキーマの違反には、違反した項目のスキーマの `title`・`description`・`x-rules`・`examples`・`x-bad-examples` のうちスキーマが持つもの |
| DocumentReferencedError | `on_referenced: fail` で、消す文書が他の文書の `related` から参照されている | 参照元の ID と `on_referenced: unlink` |
| DeleteNotAllowedError | Git 管理外の配信元で、種類の `documents[].writable` が削除を許していない | 種類の ID と `documents[].writable` のパス |
| LastReadNotFoundError | `list_changes` の `from` を省いたが、この会話で本文を読んだ記録が無い | `from` を渡すこと |

<!-- /table -->

`search_docs` の返す量が上限に達したときはエラーにせず、`truncated` と `next_cursor` を返します。
`notes` に、`fields` を絞るか `view: ids` で取り直す手を添えます。

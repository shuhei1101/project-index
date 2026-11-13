# 管理のMCP

管理の MCP の 7 つのツールの引数・返す内容・エラーの一覧

## 共通

接続先は `http://127.0.0.1:${PROJECT_INDEX_PORT:-8786}/_admin/mcp` で、トランスポートは HTTP（Streamable HTTP）です。
`127.0.0.1` だけで待ち受け、作業場所（`cwd`）での絞り込みは持たず、全ての配信元を扱います。
文書の MCP のツールに入る `cwd`・`session_id`・`agent_id` は、管理の MCP のツールには入りません。

<!-- table: data -->

| ツール | 種類 | 役割 |
| --- | --- | --- |
| `status` | 読み取り | 待ち受け・バージョン・端末の設定・配信元ごとの状態 |
| `reload` | 書き込み | 端末の設定と配信元の設定の読み直し |
| `restart` | 書き込み | サーバーの再起動 |
| `update` | 書き込み | project-index のクローンの更新と、必要なら再起動 |
| `check_project` | 読み取り | 配信元の設定・管理用の YAML・スクリプトの検査 |
| `try_convert` | 読み取り | 1 つのファイルの試しの変換 |
| `write_nav` | 書き込み | `project-index.yaml` の `nav` のタブ・項目の追加・修正・削除 |

<!-- /table -->

`status`・`check_project`・`try_convert` には `readOnlyHint: true` が付きます。
タイムアウトは設けません。スクリプトを実行する確かめと変換は、配信元ごとに `script_timeout_sec` で打ち切ります。

`status`・`reload`・`check_project`・`write_nav` は引数 `format`（`markdown` か `json`、既定 `markdown`）を持ちます。
`json` のときは、同じ中身を structuredContent と text に入れます。

### バージョンの比較

| 値 | 意味 |
| --- | --- |
| `current` | 設定の `version` が project-index が読めるバージョンと同じ |
| `old` | 古い。`project-index migrate` で移し替える |
| `newer` | 新しい。project-index を更新する |

### 索引の同期の件数

| フィールド | 内容 |
| --- | --- |
| `missing_refs` | `metadata` に書いた列が無い文書の件数 |
| `unindexed_files` | 管理用の YAML に無いファイルの件数。除外の条件（生成物・ロック・バイナリ・ベンダーのコード・再エクスポートや空の `__init__`）に当たるファイルは数えない |
| `missing_body_files` | ファイルが無い行の件数 |
| `unresolved_related` | `related[].to` が配信元のどの文書の ID にも当たらない関連の件数。`source` を持つ関連は数えない。内訳は `{行の id}: {文書の id}: {to}` |

呼ばれるたびに、起動時と同じ関数で求め直します。

## status

待ち受けのアドレス・project-index のバージョン・端末の設定・配信元ごとの状態を返します。

| 引数 | 型 | 既定 | 説明 |
| --- | --- | --- | --- |
| `format` | `markdown` / `json` | `markdown` | 返す形式 |

<!-- table: data -->

| 返すフィールド | 型 | 説明 |
| --- | --- | --- |
| `address` | str | 待ち受けている URL |
| `version` | str | 動いている project-index のバージョン |
| `pid` | int | サーバーのプロセス ID |
| `terminal.file` | str | 読んだ端末の設定のパス |
| `terminal.version_state` | `current` / `old` / `newer` | 端末の設定の `version` の比較 |
| `sources[].id` | str | 配信元の ID |
| `sources[].status` | `serving` / `not_served` / `disabled` | 配信中・検証で外した・`enabled: false` |
| `sources[].errors[]` | list[str] | 配信しない理由（`{キーのパス}: {理由}`）。`not_served` のとき |
| `sources[].config_version` | str / null | 配信元の設定の `version` |
| `sources[].version_state` | `current` / `old` / `newer` / null | 配信元の設定の `version` の比較 |
| `sources[].sync` | obj / null | 索引の同期の件数。`serving` のとき。配信元の検査が済んでいなければ `null` |
| `loading` | bool | 配信元を読み込んでいる間は `true`。その間の `sources[]` は空 |

<!-- /table -->

```markdown
http://127.0.0.1:8786/ project-index 0.2.0（pid 4242）
端末の設定: /home/u/.config/project-index/settings.yaml（current）
| source | 状態 | 設定のバージョン | 索引の同期 |
| --- | --- | --- | --- |
| sample | serving | 1（current） | 0 |
| broken | not_served（documents[0].paths: 必須のキーが無い） | - | - |
```

配信元が 0 件のときは、空の一覧を返します。
`status` は配信元の読み込みを待たずに答え、読み込み中は、読み込み中であることと、読み込みが終わっていない配信元を指す文書の MCP の呼び出しが待たされることを返します。
索引の同期の件数は、配信元の読み込み・読み直しと `write_docs`・`delete_docs` の後に裏で実行する検査の最後の結果です。
今のファイルで求め直すときは `check_project` を使用します。
設定のバージョンは、いま配信中の設定の値です。`default_ref` が進んだ配信元は、その配信元を使う次の要求の後に変わります。

## reload

端末の設定と配信元の設定を読み直し、配信元の一覧を差し替えます。
文書・検査・変換のキャッシュは捨てます。
`/mcp`・`/_admin/mcp` の接続は切れません。

`bind`・`port`・`state_dir` など、反映が「再起動」のキーは読み直しません。
読み直しは、端末の設定の保存と同じロックで一度に 1 つだけ行います。

| 引数 | 型 | 既定 | 説明 |
| --- | --- | --- | --- |
| `format` | `markdown` / `json` | `markdown` | 返す形式 |

| 返すフィールド | 型 | 説明 |
| --- | --- | --- |
| `added[]` | list[str] | 新しく配信を始めた配信元の ID |
| `removed[]` | list[str] | 端末の設定から無くなって配信をやめた配信元の ID |
| `not_served[].id` | str | 検証に失敗して配信していない配信元の ID |
| `not_served[].errors[]` | list[str] | `{キーのパス}: {理由}` |
| `sources[]` | list | 読み直した後の配信元ごとの状態。`status` の `sources[]` と同じスキーマ |

検証に失敗した配信元があっても、外して正常終了します。

| エラー | 発生条件 |
| --- | --- |
| `TerminalConfigInvalidError` | 端末の設定が無い・スキーマに違反する。違反を全て返し、配信元の一覧は読み直す前のまま |

## restart

応答を返してからサーバーを止め、同じプロセス ID・同じ環境変数で `project-index serve` を起動し直します。
`/mcp`・`/_admin/mcp` の接続は切れるので、つなぎ直します。
起動し直したプロセスは、配信元を読む前に待ち受けを始めます。
配信元は 1 つずつ読み込まれ、読み込みが終わっていない配信元を指す文書の MCP の呼び出しと読み取り API の文書の取得は、その配信元の読み込みが終わるまで待たされます。
再起動の結果は、つなぎ直した後の `status` で、`loading` が `false` になってから確かめます。

処理中の要求は、`script_timeout_sec` の 1.5 倍を上限に待ちます。
過ぎたら残りの要求を切って止めます。
起動に失敗したときは、`project-index serve` の終了コードで止まり、次のセッションの SessionStart のフックが起動し直します。

引数はありません。

| 返すフィールド | 型 | 説明 |
| --- | --- | --- |
| `pid` | int | 起動し直した後も変わらないプロセス ID |
| `restarting` | bool | 常に `true` |

| エラー | 発生条件 |
| --- | --- |
| `RestartInProgressError` | 前の `restart`・`update` の再起動がまだ終わっていない |

## update

端末の設定の `clone` で `git pull --ff-only` と `uv sync` を実行し、端末の設定の移し替えが要らなければ起動し直します。
新しいバージョンのコードで `{clone}/.venv/bin/python -m project_index migrate --plan` を実行し、当てる手順があれば移し替えが要るとします。
`git pull`・`uv sync`・`migrate --plan` は、それぞれ 300 秒で打ち切ります。

引数はありません。

| 返すフィールド | 型 | 説明 |
| --- | --- | --- |
| `previous_version` | str | 更新する前の project-index のバージョン |
| `version` | str | 更新した後のクローンのバージョン。`updated: false` のときは `previous_version` と同じ |
| `updated` | bool | 新しい commit を取り込んだか |
| `migration_needed` | bool | 端末の設定の移し替えが要るか。`true` のときは再起動しない |
| `restarting` | bool | 応答の後に起動し直すか |

`migration_needed: true` のときは、`project-index migrate` を実行してから `restart` を呼びます。
配信できなかった配信元と、配信元の設定のバージョンの新旧は、起動し直した後の `status` で確かめます。

| エラー | 発生条件 |
| --- | --- |
| `UpdateFailedError` | `git pull --ff-only`・`uv sync`・`migrate --plan` が 0 以外で終わった、または打ち切った。失敗したコマンドと標準エラーを返し、再起動しない。クローンに commit していない変更があるときも、変更に触らずこのエラーを返す |
| `RestartInProgressError` | 再起動か更新がまだ終わっていない |

手順は [project-indexを更新する](./project-indexを更新する.md) にあります。

## check_project

配信元の `project-index.yaml` と管理用の YAML・スクリプトを検査し、違反・設定のバージョンの新旧・索引の同期の件数を返します。
端末の設定に無い配信元も検査できます。
起動と `reload` の配信元の検証と同じ関数を使い、結果は配信中の配信元の状態に反映せず、ファイルも書き換えません。
`records` を持つ行は、`schema` から `properties.{records}.items` を取り出せない組み合わせを `documents[{番号}].schema` の違反にします。
`paths_base` が無いフォルダ・設定ファイルのフォルダより下や横・リポジトリの直下より上を指すときは `paths_base` の違反、`documents[].paths[]` が基準のフォルダの外を指すときは `documents[{番号}].paths[{番号}]` の違反にします。

| 引数 | 型 | 必須 | 既定 | 説明 |
| --- | --- | --- | --- | --- |
| `path` | str | ✅ | - | 配信元のフォルダか、その `project-index.yaml` の絶対パス |
| `config` | str | - | `path` の `project-index.yaml` を読む | ファイルに記載する前の `project-index.yaml` の中身（YAML の文字列）。記載する前の設定を確かめるときに渡す |
| `format` | `markdown` / `json` | - | `markdown` | 返す形式 |

<!-- table: data -->

| 返すフィールド | 型 | 説明 |
| --- | --- | --- |
| `path` | str | 検査した配信元のフォルダ |
| `registered_id` | str / null | 端末の設定の `sources` に同じフォルダの行があれば、その ID |
| `config_version` | str / null | `project-index.yaml` の `version` |
| `version_state` | `current` / `old` / `newer` / null | project-index が読めるバージョンとの比較 |
| `violations[].path` | str | 違反したキーのパス（`documents[0].paths`） |
| `violations[].rule` | str | 違反の理由 |
| `violations[].doc` | str / null | 違反した文書のパス。`alias_type` を持つ行の文書のエイリアスのキーを、取り込んだエイリアスのスキーマで検証した違反に入る。`project-index.yaml` のキーの違反は `null` |
| `missing_paths[]` | list[str] | `documents[].paths` などが指して無いフォルダ・ファイル |
| `script_errors[].script` | str | 確かめに失敗したスクリプトのパス |
| `script_errors[].reason` | str | 終了コードと標準エラーの要約 |
| `sync` | obj | 索引の同期の件数。`metadata` の列の欠け・索引に無いファイル・ファイルが無い行・どの文書にも当たらない関連 |
| `sync.items[]` | list | 件数の内訳（種類とパス）。先頭 50 件まで。件数は全件を数える |
| `warnings[].path` | str | 警告したキーのパス（`nav.tabs[2].items[0].auto.filter`） |
| `warnings[].rule` | str | 警告の理由。`nav` の `auto` の条件がどの文書にも当たらないときは、タブの名前と条件 |
| `alias_schema_version` | str | 取り込んだエイリアスのスキーマの取り込み元のタグ（`shuhei1101/alias-inject` のタグ） |

<!-- /table -->

```markdown
/home/u/repo/sample（登録済み: sample）
設定のバージョン: 1（current）

違反: なし
索引の同期: 管理用の YAML に無いファイル 1 件
- unindexed_files: docs/memo.md
```

違反と警告があっても、それらを返して正常終了します。

| エラー | 発生条件 |
| --- | --- |
| `ConfigNotFoundError` | `path` に `project-index.yaml` も `dev-docs.yaml` も無く、`config` も渡していない |
| `ConfigParseError` | `project-index.yaml` か `config` が YAML として読めない。読めなかった行と理由を返す |

## try_convert

配信元の 1 つのファイルを、その種類が指す `converters[]` のスクリプトで、読み取り API の文書の取得と同じ変換で Markdown にして返します。
書き込まず、変換のキャッシュも残しません。

| 引数 | 型 | 必須 | 既定 | 説明 |
| --- | --- | --- | --- | --- |
| `path` | str | ✅ | - | 配信元のフォルダか、その `project-index.yaml` の絶対パス |
| `file` | str | ✅ | - | 変換するファイルの、配信元からの相対パス |
| `config` | str | - | `path` の `project-index.yaml` を読む | ファイルに記載する前の `project-index.yaml` の中身（YAML の文字列） |

| 返すフィールド | 型 | 説明 |
| --- | --- | --- |
| `kind` | str | 当たった文書の種類 |
| `converter` | str | 使った変換スクリプトのパス |
| `markdown` | str | 変換した Markdown |

| エラー | 発生条件 |
| --- | --- |
| `DocumentNotFoundError` | `file` が無い、どの文書の種類の範囲にも当たらない、または配信元のフォルダの外を指している |
| `ConverterNotDefinedError` | `file` の文書の種類が `converters[]` を指さない。値は読み取り API の文書の取得で確かめる |
| `ConvertScriptError` | 変換スクリプトが 0 以外で終わった、または `script_timeout_sec` を超えた。終了コードと標準エラーを返す |
| `ValidationFailedError` | 配信元の設定に違反か動かないスクリプトがある。`check_project` で確かめる |
| `ConfigNotFoundError` | `path` に `project-index.yaml` も `dev-docs.yaml` も無く、`config` も渡していない |
| `ConfigParseError` | `project-index.yaml` か `config` が YAML として読めない。読めなかった行と理由を返す |

## write_nav

配信元の `project-index.yaml` の `nav` だけを、タブ・項目の追加・修正・削除で書き換えます。
操作を全て当てた後の `nav` を 1 回だけ `project-index.yaml` のスキーマと条件の検証（`search_docs` の `filter` と同じ）に通し、通ったときだけ書き換えます。
`nav` 以外のキーとコメントはそのまま残し、commit はしません。
配信中の配信元には、`default_ref` へ commit された後の要求から入ります。

<!-- table: data -->

| 引数 | 型 | 必須 | 既定 | 説明 |
| --- | --- | --- | --- | --- |
| `path` | str | ✅ | - | 配信元のフォルダか、その `project-index.yaml` の絶対パス（作業中はワークツリー） |
| `operations[]` | list | ✅ | - | 並べた順に当てる操作。1 件以上 |
| `operations[].op` | `add` / `update` / `remove` | ✅ | - | 追加・修正・削除 |
| `operations[].tab` | str | ✅ | - | 対象のタブの名前（`nav.tabs[].title`） |
| `operations[].item` | str | - | なし（タブそのものが対象） | タブの中の `group` の名前。入れ子の group は `>` で区切る（`設計 > MCP`）。`add` では最後の名前が作る group、それより前が追加先の group。名前を持たない `auto`・`page` の項目は指せず、入っている group かタブの `items` を置き換えて書く |
| `operations[].value` | obj | `add`・`update` で ✅ | - | タブか項目の中身（`project-index.yaml` の `nav` と同じ書式）。`update` は渡したキーだけを置き換える |
| `format` | `markdown` / `json` | - | `markdown` | 返す形式 |

<!-- /table -->

項目はタブと group の名前でだけ指し、添字では指しません。
同じ `operations` の前の操作で並びが変わっても、指す先はずれません。

| 返すフィールド | 型 | 説明 |
| --- | --- | --- |
| `path` | str | 書き換えた `project-index.yaml` のパス |
| `nav` | str | 書いた後の `nav`（YAML のまま） |
| `counts[].path`・`counts[].count` | str・int | `auto` のキーのパスと、その条件に当たる文書の数。`path` のフォルダの文書で数える |
| `warnings[]` | list | `check_project` の `warnings[]` と同じ。どの文書にも当たらない条件も書いたうえで警告する |

| エラー | 発生条件 |
| --- | --- |
| `NavInvalidError` | 書いた後の `nav` が `project-index.yaml` のスキーマか条件の検証に通らない。違反したキーのパスと理由を返す |
| `InvalidArgumentError` | `update`・`remove` で指したタブ・group が無い、`item` が `auto`・`page` に当たる、`add` で同じ名前のタブ・group がある、`add`・`update` で `value` が無い、端末の設定の `sources[].config` で `path` より後に重ねた設定の YAML が `nav` を持つ。今のタブ・group の名前の一覧（重ねた設定のときはそのファイルのパス）を返す |
| `ConfigNotFoundError` | `path` に `project-index.yaml` が無い |
| `ConfigParseError` | `project-index.yaml` が YAML として読めない。読めなかった行と理由を返す |

どのエラーでもファイルは書き換えません。

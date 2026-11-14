# CLI

project-index serve・project-index migrate・project-index files・project-index prompt-doc のサブコマンド・引数・終了コード

## 共通

`project-index` コマンドは `serve`・`migrate`・`files`・`prompt-doc` のサブコマンドを持ちます。
`project-index --version` で project-index のバージョンを表示します。

## project-index serve

端末の設定を読み、検証に通った配信元を 1 プロセス・1 ポートで、読み取り API・文書の MCP（`/mcp`）・管理の MCP（`/_admin/mcp`）に配信します。
引数は持たず、環境変数で変えます。

| 環境変数 | 既定 | 説明 |
| --- | --- | --- |
| `PROJECT_INDEX_CONFIG` | `${XDG_CONFIG_HOME:-~/.config}/project-index/settings.yaml` | 端末の設定のパス |
| `PROJECT_INDEX_PORT` | 端末の設定の `port`（既定 `8786`） | 待ち受けのポート。設定の `port` より優先する |
| `XDG_CONFIG_HOME` | `~/.config` | `PROJECT_INDEX_CONFIG` が無いときに端末の設定を探すフォルダの親。空の文字列か相対パスは未設定として扱う |
| `PROJECT_INDEX_STATE_DIR` | 端末の設定の `state_dir` | 状態の置き場。端末の設定の `state_dir` より優先する |
| `XDG_STATE_HOME` | `~/.local/state` | `PROJECT_INDEX_STATE_DIR` と `state_dir` が無いときの状態の置き場の親。空の文字列か相対パスは未設定として扱う |
| `PROJECT_INDEX_PROMPTS_DIR` | クローンの直下の `content/prompts/` | 文書の MCP の instructions・2 つの MCP のツールの description のプロンプトの YAML を読むフォルダ |

```bash
PROJECT_INDEX_CONFIG=/tmp/x/settings.yaml PROJECT_INDEX_PORT=8786 project-index serve
```

標準出力に、待ち受けたアドレスと配信している配信元の ID を出します。
検証に失敗した配信元は外して待ち受け、`{id}: {キーのパス}: {理由}` をエラーログに記録します。

| 終了コード | 意味 |
| --- | --- |
| 2 | 端末の設定が無い、またはスキーマに違反する。標準エラーに `{ファイル}: {キーのパス}: {理由}` を全て出す |
| 3 | ポートが使用中。標準エラーにポートの番号と、`PROJECT_INDEX_PORT` で変えられることを出す |
| 4 | プロンプトの YAML が無い・読めない・スキーマに違反する・描画できない。標準エラーに `{ファイル}: {キーのパス}: {理由}` を全て出す |

待ち受けた後は、停止の合図まで終わりません。
同じポートで待ち受けられるプロセスは 1 つだけで、後から起動したプロセスは終了コード 3 で終わります。

## project-index migrate

端末の設定か配信元の `project-index.yaml` の `version` を、project-index が参照できるバージョンと比べ、移し替えの手順を古い順に当てます。
対象の `version` より新しく、project-index が参照できるバージョン以下の手順を全て当て、新しいスキーマで検証してから 1 回だけ書き込みます。
動いているサーバーには反映しません。
端末の設定を移し替えたら `restart`、配信元の設定を移し替えたら `reload` を呼びます。

<!-- table: data -->

| オプション | 既定 | 説明 |
| --- | --- | --- |
| `--plan` | 適用する | 当てる手順の一覧を出して終わる。書き換えない |
| `--record` | - | 手順を当てず、`version` だけを今のバージョンに書き換える。手で移し替えたときに使う。`--plan` とは併用しない |
| `--source` | `PROJECT_INDEX_CONFIG` が指す端末の設定 | 配信元の `project-index.yaml` のパス。渡すとその配信元の設定を対象にする |
| `--allow-destructive` | 破壊的な手順があれば止める | キーの削除など、値を捨てる手順も当てる |

<!-- /table -->

```bash
project-index migrate --plan
project-index migrate --source ~/repo/sample/project-index.yaml --allow-destructive
```

`--plan` は当てる手順を `{バージョン}: {手順の説明}` の 1 行ずつで出し、破壊的な手順には `[destructive]` を付けます。
適用は、当てた手順とバックアップのパスを出します。
バックアップは適用の前に必ず取り、同じフォルダへ `{ファイル名}.bak-{時刻}` で残します。成功しても消しません。

端末の設定は動いているサーバーと同じファイルなので、書き換えの前後でファイルの中身を比べ、変わっていたら書かずに失敗とします。

<!-- table: data -->

| 終了コード | 意味 | 動き |
| --- | --- | --- |
| 0 | 正常（当てる手順が無いときも含む） | - |
| 2 | 対象の設定が無い・YAML として読めない・`version` が無い | 何も書き換えず、バックアップも作らない |
| 4 | 手順の途中で失敗した、または当てた結果が新しいスキーマに違反した | ファイルに触らず、失敗した手順と理由を標準エラーに出す |
| 5 | 当てる手順に破壊的なものがあり、`--allow-destructive` が無い | ファイルに触らず、破壊的な手順を標準エラーに出す |
| 6 | 対象の `version` が project-index が参照できるバージョンより新しい | project-index の更新を案内する |

<!-- /table -->

終了コード 3 は `project-index serve` のポート使用中に使うため、`migrate` は使いません。

### 移し替えの手順

手順はパッケージに入れ、`src/project_index/migrations/{settings|project-index}/{バージョン}/steps.yaml` に置きます。
`settings` は端末の設定、`project-index` は配信元の設定を、そのバージョンへ上げる手順です。
`steps.yaml` は `steps:` の下に、次のキーを持つ行を並べます。

<!-- table: data -->

| キー | 説明 |
| --- | --- |
| `op` | `rename`（キーの改名）・`add`（無いキーだけを既定値つきで追加）・`delete`（キーの削除。`value` が無いときだけ破壊的な手順）・`lift`（値の引き上げ）・`unwrap`（値の取り出し） |
| `path` | キーのパス。ドットで結び、配列の要素の子は `sources[].scope` のように書く。末尾の `*` は親の辞書の全てのキー |
| `to` | 新しいキー。`rename` では同じ親の下のキー名、`lift` では親の辞書を持つ辞書の下のキー名 |
| `value` | `add` では既定値（キーが既にあれば書き換えない）、`delete` では削除する値（値が一致するときだけ削除する） |
| `match` | `lift`・`unwrap` で、値が辞書でこのキーと値を全て持つときだけ当てる。無ければ辞書の値に当てる |
| `take` | `lift`・`unwrap` で、辞書の値から取り出すキー。`unwrap` で辞書がこのキーを持たないときは元のキー名を使う |
| `description` | `--plan` に出す 1 行の説明 |

<!-- /table -->

`rename` は同じ位置で改名し、コメントを残します。
改名先のキーが既にあるときは失敗とします。

### 配信元の設定の移し替え

`--source` は、配信元の `project-index.yaml` を `version: "3"` の書き方へ移し替えます。

`version: "2"` の手順は、前の書き方の `type: yaml` を削除し、`metadata` の列の指定を列名の文字列にし、`metadata` の `alias_type` を行の `alias_type` にします。
この手順は破壊的ではありません。

`version: "3"` の手順は、最上位の `tags`（タグのマスター）を削除します。
値を捨てる破壊的な手順なので、`--allow-destructive` が要ります。
`tags` を持たない設定でも、`version: "2"` 以前から移すには `--allow-destructive` が要ります。
タグのマスターのファイルは消しません。

機械的に移せない設定（`type: markdown` の行・`defaults[]`・`alias_type` 以外の値を固定した `metadata`）が残るときは、`project-index.yaml` を書き換えず、終了コード 4 で止めます。
違反したキーのパスと、`/project-index:setup` で管理用の YAML の行へ移す案内を標準エラーに出します。

## project-index files

範囲の glob に当たるファイルのうち、除外の条件に当たらないもの（管理用の YAML に載せるファイル）を出します。
`project-index.yaml` の有無に依らず呼べ、ファイルは書き換えません。
`/project-index:setup` が、管理用の YAML に行を作るファイルを求めるのに使います。

| オプション | 必須 | 既定 | 説明 |
| --- | --- | --- | --- |
| `--root` | ✅ | - | 配信元のフォルダのパス |
| `--paths` | ✅ | - | 範囲の glob（`--root` からの相対）。繰り返して渡せる。`documents[].paths` に記載する値と同じ書き方 |
| `--exclude` | - | なし（除外の条件だけで外す） | 外すファイル名の glob。繰り返して渡せる。`documents[].exclude[]` と同じ書き方 |

```bash
project-index files --root ~/repo/sample --paths 'src/**'
```

標準出力に、載せるファイルの `--root` からのパスを 1 行ずつ、パスの昇順で出します。
載せるファイルが 0 件のときも、空の出力で終了コード 0 です。

除外の条件は [文書のメタデータ](./コアコンセプト-文書のメタデータ.md) の「載せるファイルの判定」にあります。
`.git`・`node_modules`・`__pycache__`・`.venv`・`.claude/worktrees` のフォルダとシンボリックリンクは辿りません。

| 終了コード | 意味 |
| --- | --- |
| 2 | `--root` が無いか、フォルダでない。標準エラーに渡したパスを出す。`project-index migrate` の設定の違反と同じ値 |

## project-index prompt-doc

標準入力のプロンプトの YAML 1 件（キーは `templates/prompt.schema.yaml`）を Markdown にして標準出力に出します。
配信元の `converters[].run` から呼ぶ変換で、引数は持たず、ファイルは書き換えません。
行の書き方は [設定](./設定.md) の「雛形」にあります。

```bash
project-index prompt-doc < content/prompts/node/reflection.yaml
```

Markdown は、`name` の見出し・`kind` と `lang` のバッジ・`description`・タグと出力の行のあとに、次のセクションを並べます。

| セクション | 内容 |
| --- | --- |
| 変数 | `vars` を `character.display_name`・`traits[].name` のようなパスで 1 行ずつ展開した表。列は変数・型・必須・例・説明・出どころ |
| テンプレート | 部品ごとのセクションに、`role`・`tags`・`when` のバッジと Jinja2 の本文。本文の `{{ 変数 }}` に説明・型・例のツールチップが付く |
| 例 | 「既定の例」（各変数の `example`）と `examples[]` の組ごとのセクションに、`when` が真の部品だけを描画した結果。`kind: llm` は `role` ごとのメッセージに分け、使わなかった部品と字数を出す。2 つ目以降の組は閉じた状態 |

部品と例の組のセクションには、`parts[].texts[]` の言語のタブを置きます。
タブは注入する言語（`lang`）を先頭に並べ、全ての部品の言語が 1 つだけの文書にはタブを置きません。

| 注意書き | 出る場所 |
| --- | --- |
| `[!CAUTION]` | 未定義の変数・型の合わない値・描画中の例外の組のセクション。他の組は描画する |
| `[!CAUTION]` | Jinja2 の構文が誤った部品のセクションと、全ての例の組のセクション |
| `[!WARNING]` | `kind: hook` で、描画した結果が 1,000 字を超えた組のセクション |

| 終了コード | 意味 |
| --- | --- |
| 0 | 正常。描画できない組・字数を超えた組・構文の誤った部品があっても 0 |
| 1 | YAML として読めない、または変換に使うキーが無い・型が違う。標準出力には何も出さず、標準エラーに理由とキーのパスを出す |
| 2 | 引数を渡した |

---
name: setup
description: フォルダを project-index の配信元として端末の設定に登録する。2 回目以降は、範囲のファイルと管理用の YAML を突き合わせて追加・削除・改名を修正する
argument-hint: "[path]"
---

# setup

`$ARGUMENTS` は配信元のフォルダ。省くと今の作業場所。
質問は AskUserQuestion で、既定値を推奨の選択肢にして聞く。
管理の MCP のツール（`check_project`・`reload`）は `mcp__plugin_project-index_project-index-admin__` で始まる名前、`write_docs` は文書の MCP（`mcp__plugin_project-index_project-index__write_docs`）にある。

## 手順

1. 端末の設定を確認する。
   - 端末の設定が無ければ、`/project-index:global-setup` を案内して止まる
   - 端末の設定の `clone` の値を以降 `{clone}` と呼ぶ
   - `{clone}/.venv/bin/python -m project_index --version` の番号に `v` を付けた値を以降 `{tag}` と呼ぶ（`project-index 0.2.0` なら `v0.2.0`）

2. 配信元の設定を決める。
   - `{path}/project-index.yaml` がある場合、`check_project` を呼ぶ。`version_state` が `old` なら、`{clone}/.venv/bin/python -m project_index migrate --source {path}/project-index.yaml --plan` で手順を示し、了承されたら `{clone}/.venv/bin/python -m project_index migrate --source ...` で適用する。`newer` なら、管理の MCP の `update` で project-index を更新するよう案内して止まる。違反があれば、キーのパスと理由を示す。違反が `type`・`defaults`・`metadata` の値（`migrate` で移せない設定）なら手順 3 以降で移し、それ以外の違反では止まる。端末の設定は書き換えない
   - `{path}/project-index.yaml` が無い場合、手順 3 以降で `{clone}/templates/project-index.yaml` から作る（YAML でない範囲の配信元）

3. 権限と範囲を聞く。端末の設定の `sources[]` に同じ配信元の行が既にあるときは、今の値を示して変えるかだけを聞く。

   | 質問 | 既定 |
   | --- | --- |
   | 書き込める作業場所（`scope.write`）。パスか glob | `{path}` |
   | 参照できる作業場所（`scope.read`） | `{path}/**` |
   | 検索できるようにするファイル（`documents[].paths`）。`project-index.yaml` が無いときだけ聞く | `**/*.md`。`.git`・`node_modules`・`.claude/worktrees` の下は除く |
   | 実装のパスを持つ設計書の種類とキー。`project-index.yaml` が無いときだけ聞く（ある配信元は手順 4 で聞く） | 無し |

4. YAML でない範囲を管理用の YAML の行にする。
   - `{clone}/.venv/bin/python -m project_index files --root {path} --paths {範囲の glob}` で、範囲のうち管理用の YAML に記載するファイルを求める（`--paths` は繰り返せる。生成物・ロック・バイナリ・ベンダーのコード・再エクスポートや空の `__init__` と、`.git`・`node_modules`・`.claude/worktrees` の下は含まれない）。管理用の YAML（`files.yaml`）の行と突き合わせる
     - 範囲の glob は、`project-index.yaml` が無いときは手順 3 で回答した範囲にする
     - `project-index.yaml` があるときは、`records: files` の行ごとに 1 回ずつ呼び、範囲の glob を `{管理用の YAML のフォルダ}/**` にする（行の `paths` の値は指定しない）。その行の `exclude` を 1 つずつ `--exclude` で指定する。行をまとめて 1 回で呼ばない
   - 結果は次の候補にする

     | 突き合わせの結果 | 候補 |
     | --- | --- |
     | 管理用の YAML に無いファイル | 仮のメタデータと関連の候補を付けて行を追加 |
     | ファイルが無い行 | 行を削除 |
     | 名前が変わったファイル | 行のパスを新しくし、メタデータは残す。Git の配信元は `git diff --name-status -M` のリネームの検出、Git 管理外は内容のハッシュの一致で見つける |

   - `project-index.yaml` があるときは、次の候補も加える

     | 状況 | 候補 |
     | --- | --- |
     | 1 行目が `# yaml-language-server: $schema=https://raw.githubusercontent.com/shuhei1101/project-index/{tag}/schemas/project-index.schema.json` でない（行が無い・タグが `{tag}` と違う） | 1 行目をその行にする（行が無ければ 1 行目に入れる） |
     | `type: markdown` の行・`defaults[]`・`alias_type` 以外の固定値の `metadata` | 範囲の Markdown のフロントマターと `defaults[]` の値を管理用の YAML の行へ移し、`documents` の行を管理用の YAML を参照する行（`records: files`・`body_file: path`）にする。Markdown からフロントマターを削除し、`version` を新しくする |

   - 仮のメタデータは、見出しと冒頭から付ける。管理用の YAML の行が既にメタデータを持つファイルには付けない
     - `name`: 何のファイルかを表す日本語の名詞句。クラス名・ファイル名の繰り返しにしない
     - `description`: 「何を受け持つか」と「どんなときに参照するか」の 1 文。関数の一覧・実装の手順は入れない
     - `tags`: `topic`（扱う概念）と `tool`（使用するライブラリ・外部サービス）で、付けるタグがあるときだけ付ける
   - 追加する行があり、まだ聞いていないときは、実装のパスを持つ設計書の種類とキーを聞く（既定は無し）
   - 追加する行に関連の候補を付ける

     | 関連 | 付ける行 |
     | --- | --- |
     | `tests` | テストのファイル。ファイル名から `test_` の接頭辞（`_test`・`.test` の接尾辞）を除いた名前のコードを指す（`to` は文書の ID で、指すコードの配信元の直下からの拡張子付きのパス）。同じ名前のコードが範囲に無ければ付けない |
     | `implements` | 回答した種類の文書を `search_docs`（`filter` は `kind`、`format: json`）で引き、そのキーの値とパスが一致するコード。その設計書を指す。種類とキーが無しなら付けない |

   - 配信元の直下と、配信元の中のプラグインのルート（`.claude-plugin/plugin.json` を持つフォルダ）で `content/prompts/` を探す。見つけたフォルダのうち、`content/prompts/**/*.yaml`（プラグインのルートは `{ルート}/content/prompts/**/*.yaml`）を `paths` に持つ行が `project-index.yaml` に無いものごとに、次の候補を加える
     - `{clone}/templates/project-index.yaml` の `prompts` の行の `paths` をそのフォルダにした `documents` の行。プラグインのルートの行は `id` を `prompts-{ルートのフォルダ名}` にする
     - `converters[]` に `prompt-doc` の行が無ければ、雛形の `prompt-doc` の行
     - `nav` の、プロンプトの行を `auto` で並べ `group_by: kind` でまとめる `プロンプト` のタブ。`nav` が無ければ、今の `documents` の行ごとの `auto` のタブ（`title` は行の `title`）を先に並べる
   - 追加・削除・改名と、仮のメタデータ・関連・プロンプトの行の候補を表で示し、記載してよいかを聞く。断られたら何も書き換えずに止まる

5. 確認が済んだものを記載する。
   - `project-index.yaml` が無い場合、`{clone}/templates/project-index.yaml` から `project-index.yaml` を作り、1 行目のスキーマの行のタグを `{tag}` に、`name`・`description`・`files` の行の `paths` を決めた値にする。雛形の `prompts` の行と `converters[]` は削除する。`{clone}/templates/files.schema.yaml` を `{path}/schemas/files.schema.yaml` にコピーする
   - プロンプトの行の候補が了承された場合、`project-index.yaml` に `documents`・`converters[]`・`nav` の行を記載し、`{clone}/templates/prompt.schema.yaml` を `{path}/schemas/prompt.schema.yaml` にコピーする
   - 管理用の YAML の行は、`write_docs` で記載する（配信元が登録済みのとき）。登録前の配信元は、`templates/files.schema.yaml` に沿って `files.yaml` を直接書く
   - `check_project`（`path` は配信元のフォルダ）を呼び、違反が無いことを確認する。違反があれば示して止まり、端末の設定は書き換えない

6. 端末の設定の `sources[]` に行を記載し、配信を始める。
   - 端末の設定の `sources[]` に、`config`（`{path}/project-index.yaml` の絶対パス）・`scope.write`・`scope.read` の行を記載する。同じ配信元の行があれば、その行を修正する
   - 管理の MCP の `reload` を呼ぶ。`/mcp` のセッションは切れない
   - 追加した配信元と `check_project` の結果（索引の同期の件数を含む）を示す

## 開発中の使用方法

範囲のファイルを作った・削除した・改名したときは、この手順を待たず、作業中のエージェントが管理用の YAML の行を `write_docs` で修正する。

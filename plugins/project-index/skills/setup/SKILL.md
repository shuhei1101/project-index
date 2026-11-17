---
name: setup
description: フォルダを project-index の配信元として端末の設定に登録する。2 回目以降は、範囲のファイルと管理用の YAML を突き合わせて追加・削除・改名を修正し、中身が変わったファイルのメタデータを見直す
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

2. 運用と配信元の設定を決める。
   - 端末の設定の `sources[]` に、`config` の先頭のファイルが `{path}` にある行があれば、その行の `storage.type` が `disk` ならローカル運用、それ以外はコミットする運用にする。行が無ければ、運用（コミットする・ローカル運用）を聞く。既定はコミットする
   - ローカル運用は、project-index のために追加するファイルを全て `*.local.*` の名前にし、Git に無視させる運用。コミットできないリポジトリで選ぶ
   - 配信元の設定のファイルを以降 `{config}` と呼ぶ。コミットする運用は `{path}/project-index.yaml`、ローカル運用は `{path}/project-index.local.yaml`。ローカル運用では、管理用の YAML を `files.local.yaml`、スキーマを `schemas/{名前}.schema.local.yaml`、スクリプトを `*.local.*` の名前にする
   - 以降の `check_project` は、`path` に `{config}` を渡し、ローカル運用では `storage_type: disk` も渡す
   - `{config}` がある場合、`check_project` を呼ぶ。`version_state` が `old` なら、`{clone}/.venv/bin/python -m project_index migrate --source {config} --plan` で手順を示し、了承されたら `{clone}/.venv/bin/python -m project_index migrate --source {config}` で適用する。`newer` なら、管理の MCP の `update` で project-index を更新するよう案内して止まる。違反があれば、キーのパスと理由を示す。違反が `type`・`defaults`・`metadata` の値（`migrate` で移せない設定）なら手順 3 以降で移し、それ以外の違反では止まる。端末の設定は書き換えない
   - `{config}` が無い場合、手順 3 以降で `{clone}/templates/project-index.yaml` から作る（YAML でない範囲の配信元）

3. 権限と範囲を聞く。端末の設定の `sources[]` に同じ配信元の行が既にあるときは、今の値を示して変えるかだけを聞く。

   | 質問 | 既定 |
   | --- | --- |
   | 書き込める作業場所（`scope.write`）。パスか glob | `{path}` |
   | 参照できる作業場所（`scope.read`） | `{path}/**` |
   | 検索できるようにするファイル（`documents[].paths`）。`{config}` が無いときだけ聞く | `**/*`。`.git`・`node_modules`・`.claude/worktrees` の下は除く |
   | Git が無視するファイルを除外するか。`{config}` が無く、ローカル運用か Git 管理外の配信元のときだけ聞く。ファイルの列挙は `.gitignore` を参照しない | 除外しない。`.env`・`.env.*` の名前のファイルだけ除外する |
   | 実装のパスを持つ設計書の種類とキー。`{config}` が無いときだけ聞く（ある配信元は手順 4 で聞く） | 下の求め方の種類とキー。無ければ無し |

   - コミットする運用の Git の配信元では、Git が無視するファイルは `default_ref` から配信できないため、聞かずに除外する
   - 実装のパスを持つ設計書の種類とキーの既定は、YAML の文書の行の種類ごとに `search_docs`（`filter` は `kind`、`format: json`）で文書を引き、値が範囲のファイルのパスに一致するキーを持つ種類とそのキーにする

4. YAML でない範囲を管理用の YAML の行にする。
   - `{clone}/.venv/bin/python -m project_index files --root {path} --paths {範囲の glob}` で、範囲のうち管理用の YAML に記載するファイルを求める（`--paths` は繰り返せる。バイナリ・空のファイル・`*.local.*` の名前のファイルと、`.git`・`node_modules`・`.claude/worktrees` の下は含まれない）。管理用の YAML（`files.yaml`、ローカル運用は `files.local.yaml`）の行と突き合わせる
     - 範囲の glob は、`{config}` が無いときは手順 3 で回答した範囲にする
     - Git が無視するファイルを除外する場合（コミットする運用の Git の配信元か、除外すると回答した場合）、`git -C {path} ls-files --others --ignored --exclude-standard` でファイルの一覧を取り、`project-index files` の結果からその一覧のパスを除く（`--exclude` はファイル名だけに当たるため使わない）
     - 除外しないと回答した場合は、`--exclude .env --exclude '.env.*'` を渡す
     - `{config}` があるときは、`records: files` の行ごとに 1 回ずつ呼び、範囲の glob を `{管理用の YAML のフォルダ}/**` にする（行の `paths` の値は指定しない）。その行の `exclude` を 1 つずつ `--exclude` で指定する。行をまとめて 1 回で呼ばない
   - 結果は次の候補にする

     | 突き合わせの結果 | 候補 |
     | --- | --- |
     | 管理用の YAML に無いファイル | 仮のメタデータと関連の候補を付けて行を追加 |
     | ファイルが無い行 | 行を削除 |
     | 名前が変わったファイル | 行のパスを新しくし、メタデータは残す。Git のリポジトリの中の配信元（ローカル運用を含む）は `git diff --name-status -M` のリネームの検出、Git 管理外は内容のハッシュの一致で見つける |

   - `{config}` があるときは、次の候補も加える

     | 状況 | 候補 |
     | --- | --- |
     | 1 行目が `# yaml-language-server: $schema=https://raw.githubusercontent.com/shuhei1101/project-index/{tag}/schemas/project-index.schema.json` でない（行が無い・タグが `{tag}` と違う） | 1 行目をその行にする（行が無ければ 1 行目に入れる） |
     | `type: markdown` の行・`defaults[]`・`alias_type` 以外の固定値の `metadata` | 範囲の Markdown のフロントマターと `defaults[]` の値を管理用の YAML の行へ移し、`documents` の行を管理用の YAML を参照する行（`records: files`・`body_file: path`）にする。Markdown からフロントマターを削除し、`version` を新しくする |

   - 仮のメタデータは、次の段階で中身を参照して付ける。管理用の YAML の行が既にメタデータを持つファイルには付けない
     1. 範囲に目次のページ（`index`・`README`・ファイルへのリンクを多く持つページ）があれば全文を読み、分類とタグの語彙を決める。ファイルを指すリンクの文字列と同じ行の説明は、そのファイルの `name`・`description` の材料にする。目次のページが無ければ飛ばし、タグは既存のタグだけから選ぶ
     2. `{clone}/.venv/bin/python -m project_index outline --root {path} --paths {ファイル}`（`--paths` は繰り返せる）の出力（1 ファイル 1 行の JSON）で付ける。`existing_description` があれば材料にする。`next_stage` が `true` のファイルだけ次の段階へ進む
     3. 各見出しの直下の最初の段落を読む
     4. 決められなければ、コードブロックの外の文章を読む
     5. 決められなければ、全文を読む
     - `name`: 何のファイルかを表す日本語の名詞句。クラス名・ファイル名の繰り返しにしない
     - `description`: 「何を受け持つか」と「どんなときに参照するか」の 1 文。関数の一覧・実装の手順は入れない
     - `tags`: `topic`（扱う概念）と `tool`（使用するライブラリ・外部サービス）で、付けるタグがあるときだけ付ける。既存のタグ（`search_docs` の `group_by: tags`）と段階 1 の語彙から選ぶ
   - 仮のメタデータを付けた後に、`{clone}/.venv/bin/python -m project_index skew --root {path} --files-yaml {管理用の YAML} --draft {行の案}` でメタデータの偏りを洗い出す
     - `--files-yaml` は管理用の YAML ごとに繰り返す。行の案は、追加する行と見直した行の `path`（`{path}` からのパス）・`description`・`tags` を 1 行ずつ持つ JSON Lines のファイル
     - 管理用の YAML が確認の時点（`checkpoint`）を持つときは `--only-draft` も渡す
     - 出力の `similar_descriptions`（ほぼ同じ `description` の組）・`singleton_tags`（1 件だけのタグ）・`dominant_tags`（半数以上に付くタグ）ごとに、今の値と見直しの案を作る
   - `{config}` があるときは、`records: files` の行ごとに `{clone}/.venv/bin/python -m project_index changed --root {path} --files-yaml {管理用の YAML}` で、確認の時点の後に中身が変わった行のファイルを求める
     - 出力の `files` を上の段階 2〜5 で読み、メタデータの新しい案を作る。`files` に無いファイルは読まない
     - 標準エラーに起点を切り替えた旨が出たら、候補の表と一緒に示す
   - 追加する行か関連を持たない行があり、まだ聞いていないときは、実装のパスを持つ設計書の種類とキーを聞く（既定は手順 3 の求め方）
   - 追加する行と、関連を持たない行に関連の候補を付ける

     | 関連 | 付ける行 |
     | --- | --- |
     | `tests` | テストのファイル。ファイル名から `test_` の接頭辞（`_test`・`.test` の接尾辞）を除いた名前のコードを指す（`to` は文書の ID で、指すコードの配信元の直下からの拡張子付きのパス）。同じ名前のコードが範囲に無ければ付けない |
     | `implements` | 回答した種類の文書を `search_docs`（`filter` は `kind`、`format: json`）で引き、そのキーの値とパスが一致するコード。その設計書を指す。種類とキーが無しなら付けない |

     - `{clone}/.venv/bin/python -m project_index links --root {path} --paths {配信元の範囲の glob}` の出力（指す側のファイルごとの `targets`）からも候補を付ける

       | 指す側 | 指される側 | 候補を付ける行と `type` |
       | --- | --- | --- |
       | 実装のパスを持つ種類の設計書 | 管理用の YAML の行のコード | 指される側の行に、設計書を指す `implements` |
       | それ以外の種類の設計書 | 管理用の YAML の行 | 指される側の行に、設計書を指す `see_also` |
       | 管理用の YAML の行の文書 | 配信元の文書 | 指す側の行に `see_also` |

     - 設計書 → コードの向きの関連は付けない

   - 配信元の直下と、配信元の中のプラグインのルート（`.claude-plugin/plugin.json` を持つフォルダ）で `content/prompts/` を探す。見つけたフォルダのうち、`content/prompts/**/*.yaml`（プラグインのルートは `{ルート}/content/prompts/**/*.yaml`）を `paths` に持つ行が `{config}` に無いものごとに、次の候補を加える
     - `{clone}/templates/project-index.yaml` の `prompts` の行の `paths` をそのフォルダにした `documents` の行。プラグインのルートの行は `id` を `prompts-{ルートのフォルダ名}` にする
     - `converters[]` に `prompt-doc` の行が無ければ、雛形の `prompt-doc` の行
     - `nav` の、プロンプトの行を `auto` で並べ `group_by: kind` でまとめる `プロンプト` のタブ。`nav` が無ければ、今の `documents` の行ごとの `auto` のタブ（`title` は行の `title`）を先に並べる
     - 共通の型のコピー先 `{path}/schemas/common.schema.yaml`（ローカル運用は `common.schema.local.yaml`）が既にあり `$defs.id` を持たなければ、候補の表を示す前に、そのことを示して止まる。何も書き換えない
   - 追加・削除・改名と、仮のメタデータ・メタデータの偏りの見直し・関連・プロンプトの行の候補を表で示し、記載してよいかを聞く。断られたら何も書き換えずに止まる
     - 仮のメタデータの行には、決めた段階を出す。既存のタグと段階 1 の語彙のどちらにも無いタグは、新しいタグとしてまとめて示す
     - 中身が変わったファイルの行は、今の値と新しい案を並べて示し、了承された行だけを書き換える

5. 確認が済んだものを記載する。
   - `{config}` が無い場合、`{clone}/templates/project-index.yaml` から `{config}` を作り、1 行目のスキーマの行のタグを `{tag}` に、`name`・`description`・`files` の行の `paths` を決めた値にする。雛形の `prompts` の行と `converters[]` は削除する。`{clone}/templates/files.schema.yaml` を `{path}/schemas/files.schema.yaml`（ローカル運用は `files.schema.local.yaml`）にコピーする。ローカル運用では、`files` の行の `paths`・`schema` を `files.local.yaml`・`schemas/files.schema.local.yaml` にする
   - プロンプトの行の候補が了承された場合、`{config}` に `documents`・`converters[]`・`nav` の行を記載し、`{clone}/schemas/prompt.schema.yaml` を `{path}/schemas/prompt.schema.yaml`（ローカル運用は `prompt.schema.local.yaml`）にコピーする
     - その `$ref` が指す `{clone}/schemas/common.schema.yaml` を `{path}/schemas/common.schema.yaml`（ローカル運用は `common.schema.local.yaml`）にコピーする。コピー先が既にあればコピーしない
     - ローカル運用では、コピーした `prompt.schema.local.yaml` の `$ref` の `common.schema.yaml` を `common.schema.local.yaml` に書き換える
   - 管理用の YAML の行は、`write_docs` で記載する（配信元が登録済みのとき）。登録前の配信元は、`templates/files.schema.yaml` に沿って `files.yaml`（ローカル運用は `files.local.yaml`）を直接書く
   - ローカル運用では、`git -C {path} rev-parse --git-path info/exclude` の指すファイルに `*.local.*` の行が無ければ追加する。`.gitignore` は書き換えない
   - 管理用の YAML ごとに `{clone}/.venv/bin/python -m project_index checkpoint --root {path} --files-yaml {管理用の YAML}` で確認の時点を記録する。見直したファイルのうち commit していない変更を持つものを `--reviewed` で渡す（繰り返せる）
   - `check_project` を呼び、違反が無いことを確認する。違反があれば示して止まり、端末の設定は書き換えない

6. 端末の設定の `sources[]` に行を記載し、配信を始める。
   - 端末の設定の `sources[]` に、`config`（`{config}` の絶対パス）・`scope.write`・`scope.read` の行を記載する。ローカル運用では `storage: {type: disk}` も記載する。同じ配信元の行があれば、その行を修正する
   - 管理の MCP の `reload` を呼ぶ。`/mcp` のセッションは切れない
   - alias-inject の端末の設定（`${XDG_CONFIG_HOME:-~/.config}/alias-inject/settings.yaml`）があり、`{config}` が `alias_type` を持つ `documents` の行を持つときは、`global.repositories[]` の行の `config` と `{config}` を突き合わせる
     - 行と `{config}` は、Git の配信元では `git rev-parse --git-common-dir` が同じ行、Git 管理外の配信元では同じフォルダの行を対応させる
     - 対応する行の設定のファイルの名前が `{config}` と違えば、行が指すフォルダは変えずにファイル名を `{config}` の名前にする修正の候補を示す。対応する行が無ければ、`{config}` を指す行を末尾に追加する候補を示す
     - 了承されたら、同じフォルダに `settings.yaml.bak-{YYYYMMDD-HHMMSS}` のバックアップを取ってから書き換える
     - alias-inject の端末の設定が無いときは、候補を出さず、設定を作らない
   - 追加した配信元と `check_project` の結果（索引の同期の件数を含む）を示す

## 開発中の使用方法

範囲のファイルを作った・削除した・改名したときは、この手順を待たず、作業中のエージェントが管理用の YAML の行を `write_docs` で修正する。

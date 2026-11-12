---
name: global-setup
description: 端末ごとに 1 回、project-index のクローン・依存・端末の設定・Claude Code の env・起動を用意する。再インストール・端末の移行・project-index の更新のあとにも使用する
argument-hint: "[クローンのパス]"
---

# global-setup

`$ARGUMENTS` は project-index のクローンのパス。省くと聞く。
質問は AskUserQuestion で、既定値を推奨の選択肢にして聞く。

## 手順

1. 端末の設定のパスを決める。
   - 環境変数 `PROJECT_INDEX_CONFIG` があればその値、無ければ `${XDG_CONFIG_HOME:-~/.config}/project-index/settings.yaml`（`XDG_CONFIG_HOME` が空の文字列か相対パスなら `~/.config/project-index/settings.yaml`）
   - ファイルがあるかを確認する

2. 端末の設定がある場合、バージョンを確認する。
   - `{clone}/.venv/bin/python -m project_index migrate --plan` を実行する（`clone` は端末の設定の値。端末の設定に `clone` が無いときは `$ARGUMENTS`、空ならクローンの場所を聞いた値。聞いた値は、スキーマの検証で足りないキーを追加するときに再度聞かずに記載する）
   - 終了コード 6（設定が新しい）の場合、設定のバージョンと project-index のバージョンを示し、管理の MCP の `update` で project-index を更新するよう案内して止まる。端末の設定も env も書き換えない
   - 標準出力が空の場合、手順 3 へ進む
   - 標準出力に手順がある場合、手順を示す。`[destructive]` の行があるときは、適用してよいかを聞き、断られたら止まる
   - 適用する場合、`{clone}/.venv/bin/python -m project_index migrate`（破壊的な手順を許したときは `--allow-destructive` を付ける）を実行し、適用した手順とバックアップのパスを示す
   - スキーマの検証で足りないキーがあれば、そのキーだけを聞いて追加する。`sources` の行とほかのキーは変えない

3. 端末の設定が無い場合、端末の設定を作る。
   - 端末の設定の場所を聞く（既定は `${XDG_CONFIG_HOME:-~/.config}/project-index/settings.yaml`）
   - `$ARGUMENTS` が空ならクローンの場所を聞く
   - クローンが無ければ `git clone https://github.com/shuhei1101/project-index {クローンのパス}` を実行する
   - クローンで `uv sync` を実行して依存を入れる
   - `{クローン}/templates/settings.yaml` を元に、`clone` をクローンの絶対パスにした端末の設定を作る。`sources` は空にする

4. 端末の設定の場所が既定と違う場合、Claude Code の設定の env に `PROJECT_INDEX_CONFIG` を記載する。
   - 記載先は `${CLAUDE_CONFIG_DIR:-~/.claude}/settings.json` の `env`
   - `env` のほかのキーと、ファイルのほかの内容は変えない

5. `write_docs` が Markdown の値の点検に使用する mdmark の CLI が `PATH` にあるかを、`command -v mdmark` で確認する。
   - 無くても続ける（`write_docs` は点検せずに書き込む）

6. project-index を起動して、つながることを確認する。
   - 待ち受けていなければ、`{clone}/.venv/bin/python -m project_index serve` を切り離して起動する。環境変数 `PROJECT_INDEX_CONFIG` に端末の設定のパスを指定する
   - `http://127.0.0.1:${PROJECT_INDEX_PORT:-8786}/mcp` にツールの一覧（`tools/list`）を要求し、文書の MCP のツールが 6 つ返ることを確認する

7. 結果を示す。
   - 作ったもの（端末の設定のパス・env に記載したキー）と、つながった結果を出す
   - mdmark の CLI が無かったときは、`npm install -g github:shuhei1101/mdmark`（Node 24 以降）で入れると `write_docs` が Markdown の値を点検することを案内する
   - このセッションで文書の MCP を使用するには `/mcp` で再接続することを案内する
   - 配信元を登録する `/project-index:setup` を案内する

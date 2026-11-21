---
name: global-setup
description: 端末ごとに 1 回、project-index のクローン・依存・端末の設定・Claude Code の env・起動を用意する。再インストール・端末の移行・project-index の更新のあとにも使用する
argument-hint: '[クローンのパス]'
arguments:
- clone
allowed-tools:
- Bash(*.venv/bin/python -m project_index migrate --plan*)
- Bash(command -v mdmark)
- Bash(*.venv/bin/python -m project_index serve*)
---

<!-- docs/agent-flow/skill-global-setup.yaml から生成した。このファイルを修正せず、設計書を修正して再生成する -->

# 端末に project-index を用意するスキル

## 引数

| 引数 | 説明 |
| --- | --- |
| `$clone` | project-index のクローンのパス。省くと聞く |

## 手順

### 端末の設定のパスを決める

環境変数 `PROJECT_INDEX_CONFIG` があればその値、無ければ `${XDG_CONFIG_HOME:-~/.config}/project-index/settings.yaml`（`XDG_CONFIG_HOME` が空の文字列か相対パスなら `~/.config/project-index/settings.yaml`）にし、ファイルがあるかを確認する。
この後の工程の質問は AskUserQuestion で、既定値を推奨の選択肢にして聞く。

### 移し替えの手順を確認する

端末の設定があるときだけ行う。

`{clone}` は端末の設定の `clone` の値。端末の設定に `clone` が無いときは `$clone`、空ならクローンの場所を聞いた値にする（聞いた値は、スキーマの検証で足りないキーを追加するときに再度聞かずに記載する）。
終了コード 6（設定が新しい）のときは、設定のバージョンと project-index のバージョンを示し、管理の MCP の `update` で project-index を更新するよう案内して止まる。端末の設定も env も書き換えない。
標準出力が空のときは、Claude Code の env を記載する工程へ進む。
標準出力に手順があるときは手順を示し、`[destructive]` の行があれば適用してよいかを聞き、断られたら止まる。

呼ぶもの:

- コマンド `{clone}/.venv/bin/python -m project_index migrate --plan`

### 移し替えを適用する

移し替えの手順があり、適用するときだけ行う。

`{clone}/.venv/bin/python -m project_index migrate`（破壊的な手順を許可したときは `--allow-destructive` を付ける）を実行し、適用した手順とバックアップのパスを示す。
スキーマの検証で足りないキーがあれば、そのキーだけを聞いて追加する。`sources` の行とほかのキーは変えない。

### 端末の設定を作る

端末の設定が無いときだけ行う。

端末の設定の場所を聞く（既定は `${XDG_CONFIG_HOME:-~/.config}/project-index/settings.yaml`）。
`$clone` が空ならクローンの場所（`{clone}`）を聞き、クローンが無ければ `git clone https://github.com/shuhei1101/project-index {clone}` を実行する。
クローンで `uv sync` を実行して依存を入れ、`{clone}/templates/settings.yaml` を元に、`clone` をクローンの絶対パスにした端末の設定を作る。`sources` は空にする。

### Claude Code の env を記載する

端末の設定の場所が既定と違うときだけ行う。

`${CLAUDE_CONFIG_DIR:-~/.claude}/settings.json` の `env` に `PROJECT_INDEX_CONFIG` を記載する。`env` のほかのキーと、ファイルのほかの内容は変えない。

### mdmark の CLI を確認する

`write_docs` が Markdown の値の点検に使用する mdmark の CLI が `PATH` にあるかを確認する。無くても続ける（`write_docs` は点検せずに書き込む）。

呼ぶもの:

- コマンド `command -v mdmark`

### 起動してつながることを確認する

待ち受けていなければ、環境変数 `PROJECT_INDEX_CONFIG` に端末の設定のパスを指定して、project-index を切り離して起動する。
`http://127.0.0.1:${PROJECT_INDEX_PORT:-8786}/mcp` にツールの一覧（`tools/list`）を要求し、文書の MCP のツールが全て返ることを確認する。

呼ぶもの:

- コマンド `{clone}/.venv/bin/python -m project_index serve`

### 結果を示す

作ったもの（端末の設定のパス・env に記載したキー）と、つながった結果を出す。
mdmark の CLI が無かったときは、`npm install -g github:shuhei1101/mdmark#{mdmark_ref}`（`{mdmark_ref}` は端末の設定の `mdmark_ref`。無ければ `develop`。Node 24 以降）で入れると `write_docs` が Markdown の値を点検することを案内する。
このセッションで文書の MCP を使用するには `/mcp` で再接続することと、配信元を登録する `/project-index:setup` を案内する。

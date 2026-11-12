# project-indexを更新する

update と project-index migrate で project-index を更新し、端末の設定を移し替える手順

## 手順

<!-- steps -->

1. 管理の MCP の `update` を呼ぶ。
   クローンで `git pull --ff-only` と `uv sync` を実行し、新しいバージョンのコードで `project-index migrate --plan` を実行して移し替えの要否を確かめる。
2. 応答の `updated`・`migration_needed`・`restarting` で次の動きを決める（下の表）。
3. 起動し直したら、`/mcp` でつなぎ直す。
4. 管理の MCP の `status` で、新しいバージョンと配信元が `serving` であることを確かめる。

<!-- /steps -->

| 応答 | 動き |
| --- | --- |
| `updated: false` | 新しい commit が無い。何も変えず、再起動もしない |
| `migration_needed: false` | 応答を返した後に自動で起動し直す |
| `migration_needed: true` | 再起動しない。次の「端末の設定を移し替える」へ進む |

## 端末の設定を移し替える

`update` が `migration_needed: true` を返したときの手順です。

<!-- steps -->

1. 当てる手順を確かめる。
   端末の設定は書き換わらない。
   ```bash
   project-index migrate --plan
   ```
2. 手順を当てる。
   当てる前に、同じフォルダへ `{ファイル名}.bak-{時刻}` のバックアップを取る。
   ```bash
   project-index migrate
   ```
3. 管理の MCP の `restart` を呼ぶ。
4. `/mcp` でつなぎ直し、`status` で新しいバージョンと配信元を確かめる。

<!-- /steps -->

配信元の `project-index.yaml` を移し替えるときは、`--source` にそのパスを渡し、続けて `reload` を呼びます。
手で移し替えた設定は、`--record` で `version` だけを今のバージョンに書き換えます。
オプションと終了コードは [CLI](./CLI.md) にあります。

## 配信元の設定を移し替える

`project-index.yaml` の `version` が古い配信元は、起動時の警告のログと、管理の MCP の `status`・`check_project` に出ます。

<!-- steps -->

1. 当てる手順を確かめる。
   `project-index.yaml` は書き換わらない。
   ```bash
   project-index migrate --source {配信元の project-index.yaml} --plan
   ```
2. 手順を当てる。
   当てる前に、同じフォルダへ `{ファイル名}.bak-{時刻}` のバックアップを取る。
   ```bash
   project-index migrate --source {配信元の project-index.yaml}
   ```
3. 管理の MCP の `reload` を呼ぶ。
4. `/project-index:setup {配信元のパス}` を実行し、`project-index.yaml` の 1 行目のスキーマの行のタグを project-index のバージョンに書き換える。

<!-- /steps -->

機械的に移せない設定が残るときは、終了コード 4 で止まり、`project-index.yaml` は書き換わりません。
標準エラーの違反と案内のとおり、`/project-index:setup` で管理用の YAML の行へ移します。

## 失敗したとき

<!-- table: data -->

| 事象 | 動き |
| --- | --- |
| `git pull --ff-only` が失敗する（fast-forward できない・commit していない変更がある） | `update` が失敗したコマンドと標準エラーを返す。クローンに触らず、再起動もしない |
| `uv sync` が失敗する | `update` が失敗したコマンドと標準エラーを返し、再起動しない |
| 移し替えの手順が失敗する、または当てた結果がスキーマに違反する | 端末の設定を書き換えず、失敗した手順と理由を標準エラーに出す |
| 当てる手順に破壊的なもの（キーの削除）がある | 触らずに止まる。内容を確かめ、了承できれば `--allow-destructive` を付けて実行する |
| 端末の設定の `version` が project-index より新しい | 触らずに止まる。`update` で project-index を更新する |
| `restart`・`update` の再起動が終わる前に呼んだ | `RestartInProgressError` で断る。起動し直した後に呼び直す |

<!-- /table -->

起動に失敗したときは、次のセッションの SessionStart のフックが起動し直します。

# 読み取りAPI

読み取り API と端末の設定の API のエンドポイント・入出力・エラーの一覧

## 共通

接続先は `http://127.0.0.1:${PROJECT_INDEX_PORT:-8786}` で、文書の MCP・管理の MCP と同じ 1 つのポートです。
`127.0.0.1` でだけ待ち受け、認証はありません。
応答の JSON のキーは camelCase で、パス・クエリのパラメータ名は変えません。
エラーは RFC 9457 の `application/problem+json` で返し、404 は `missing`（`source`・`not_served`・`ref`・`doc`）に見つからなかったものを入れます。

## 読み取り API

<!-- table: data -->

| エンドポイント | 返すもの | 主なエラー |
| --- | --- | --- |
| `GET /sources` | 配信元ごとの ID・状態（`serving`・`not_served`・`disabled`）・配信していない理由 | - |
| `GET /sources/{source}/config?schemas=` | 配信元の設定のうち `nav`・`documents[]`（スクリプトのコマンドを除く）・`decisions.folders`・`github`・`diff`。`schemas=true` で `documents[]` の行ごとの `$ref` を解いた種類のスキーマも返す | 404（無い・配信していない配信元） |
| `GET /sources/{source}/docs?ref=&values=&fields=` | 指したリビジョン（省くと `default_ref`）の文書の ID・パス・種類・メタデータ・バージョン。`values=true` で文書の値も返す。`fields=true` で、配信元の設定の行の `metadata`・`alias_type` で解決した共通のキーも返す | 404（配信元・リビジョン） |
| `GET /sources/{source}/docs/{path}?ref=&id=` | 文書の値・種類のスキーマ・メタデータ（解決した共通のキーを含む）。管理用の YAML の行の文書は本文の文字列と本文のファイルのパスも返す。`converters[]` を指す種類は、スクリプトが出した Markdown か変換の失敗 | 404（配信元・リビジョン・文書） |
| `GET /sources/{source}/decisions` | `decisions.folders` にある検討事項の ID と、ID ごとに当たるフォルダの数 | 404（配信元） |
| `GET /sources/{source}/decisions/{id}` | ちょうど 1 つのフォルダにある検討事項の文書の本文 | 404（当たるフォルダが 0 個か 2 個以上。`reason` に `not_found`・`ambiguous`） |
| `GET /sources/{source}/search?q=&ref=&limit=` | 語を含む文書の ID・文書のファイルのパスと一致した箇所 | 400（語が空・長すぎる）・404 |
| `GET /sources/{source}/refs?commits=` | ブランチ・タグ・最近の commit。Git 管理外の配信元は `git: false` | 404（配信元） |

<!-- /table -->

`{path}` は文書のファイルのパスか本文のファイルのパスで、配信元の直下から拡張子つきで指します。
1 つの管理用の YAML の中の行の文書は、`id` に文書の ID を指して 1 つに選びます。
スキーマ駆動の Markdown への変換は行いません。値とスキーマから画面の本文を作るのは、dev-docs の画面のサーバーです。

## 端末の設定の API

<!-- table: data -->

| エンドポイント | 動き | 主なエラー |
| --- | --- | --- |
| `GET /settings/sources` | 端末の設定の `sources[]` の行と、配信元ごとの状態を返す | - |
| `PUT /settings/sources` | `sources[]` を丸ごと保存して配信元を読み直し、状態を返す | 403（別のオリジン）・422（スキーマに通らない） |
| `POST /settings/sources` | 配信元の行を 1 行追加して読み直す（201）。同じ id の行があれば追加せず、内容が同じかを返す（409） | 403・409・422 |

<!-- /table -->

`PUT`・`POST` は、`Origin` と `Sec-Fetch-Site` を持たない要求（サーバーの側からの呼び出し）と、project-index と同じオリジンの要求だけを受け、ブラウザが別のオリジンから送る書き込みを 403 で断ります。
保存は `settings.yaml` の `sources` だけを書き換え、他のキーとコメントを残します。
`PUT` で行に含めなかったキー（`enabled`・`scope.read`・`scope.write`・`outside_read`）は、ファイルの同じ配信元の行（`id`、無ければ配信元の設定の `name` で照合します）の今の値で残ります。
`GET` の行は、端末の設定の `outside_read` を `outsideRead` で返します。

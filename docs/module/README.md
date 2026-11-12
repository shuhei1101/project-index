# module

クラス・関数・データモデルの分割と依存

## 目次

<!-- table: data -->

| ページ | 概要 |
| --- | --- |
| [索引のサーバー / パッケージ](./MOD-1.yaml) | 索引のサーバーの Python パッケージ `project_index` のファイルの並びと、パッケージ全体の決まり。 |
| [プラグイン / 配布](./MOD-2.yaml) | Claude Code のプラグイン project-index と、それを掲載するマーケットプレースのファイルの並び。 |
| [索引のサーバー / 入口 / __main__.py](./MOD-3.py.yaml) | `project-index` コマンドの引数の組み立てと main。 |
| [プラグイン / ツール実行前のフック / pre_tool_use.py](./MOD-4.py.yaml) | PreToolUse のフック。文書の MCP のツールの入力に `cwd`・`session_id`・`agent_id` を上書きで入れ、`updatedInput` で返す。 |
| [プラグイン / セッション開始のフック / session_start.py](./MOD-5.py.yaml) | SessionStart のフック。ポートにつながらなければ `project-index serve` を切り離して起動し、つながれば文脈を入れず、`/clear`・圧縮のときだけ `POST /_admin/session-start` で返し済みの記録の削除を依頼する。 |
| [索引のサーバー / 入口 / __init__.py](./MOD-6.py.yaml) | インストール済みのパッケージからバージョンを引くときの配布名。 |
| [索引のサーバー / 権限と作業場所 / service.py](./MOD-7.py.yaml) | 作業場所からの権限と、MCP の引数からの読み書きする場所の解決。 |
| [索引のサーバー / 権限と作業場所 / types.py](./MOD-8.py.yaml) | 配信元の権限・作業場所・読み書きする場所・権限のレベルの型。 |
| [索引のサーバー / 管理 / render.py](./MOD-9.py.yaml) | 管理の MCP の `format: markdown` の応答の文を組み立てる。値は service.py の結果をそのまま使い、計算しない。 |
| [索引のサーバー / 管理 / service.py](./MOD-10.py.yaml) | 管理の MCP の `status`・`reload`・`check_project`・`try_convert` の中身。配信中の部品（`Handlers`）を読むだけで、`reload_config` 以外は配信元の状態を変えない。 |
| [索引のサーバー / 管理の操作 / types.py](./MOD-11.py.yaml) | 管理の MCP の `status`・`reload`・`check_project`・`try_convert` の要求と結果の型。 |
| [索引のサーバー / 変更 / compare.py](./MOD-12.py.yaml) | 変わったキー・差分の行・語の出現数の比べ方。 |
| [索引のサーバー / 変更 / render.py](./MOD-13.py.yaml) | `list_changes` の結果の Markdown。 |
| [索引のサーバー / 変更 / service.py](./MOD-14.py.yaml) | `list_changes` の区間か前回読んだ時点からの変わった文書と差分。 |
| [索引のサーバー / 変更 / types.py](./MOD-15.py.yaml) | `list_changes` の要求と結果の型。 |
| [索引のサーバー / 変換 / decisions.py](./MOD-16.py.yaml) | 配信元の `decisions.folders` から検討事項の文書を探す。 |
| [索引のサーバー / 変換 / service.py](./MOD-17.py.yaml) | `converters[]` の実行と結果の控え。 |
| [索引のサーバー / 変換 / types.py](./MOD-18.py.yaml) | 変換の結果と変換の失敗のデータモデル。 |
| [索引のサーバー / 説明 / render.py](./MOD-19.py.yaml) | `describe` の結果の Markdown。 |
| [索引のサーバー / 説明 / service.py](./MOD-20.py.yaml) | `describe` の使える配信元・説明書と種類・種類のスキーマ。 |
| [索引のサーバー / 説明 / source_checks.py](./MOD-21.py.yaml) | 配信元ごとの検査（同期のずれ・エイリアスのキーの違反・`nav` の警告）の結果を持ち、`describe` の警告に渡す。 |
| [索引のサーバー / 説明 / types.py](./MOD-22.py.yaml) | `describe` の要求と結果の型。 |
| [索引のサーバー / 説明 / warnings.py](./MOD-23.py.yaml) | 引数なしの `describe` に添える警告（使える配信元の同期のずれ・古い設定と、配信していない配信元）。 |
| [索引のサーバー / 文書のストア / aliases.py](./MOD-24.py.yaml) | エイリアスのキーの検証と、用語の収集・照合。 |
| [索引のサーバー / 文書のストア / fields.py](./MOD-25.py.yaml) | 項目のパスの解釈と、項目の値の取得・設定・削除・メタデータの解決。 |
| [索引のサーバー / 文書のストア / indexable.py](./MOD-26.py.yaml) | たどるフォルダと、載せるファイルの判定。 |
| [索引のサーバー / 文書のストア / loader.py](./MOD-27.py.yaml) | ファイルの収集と、ファイルからの文書の作成。 |
| [索引のサーバー / 文書のストア / schema.py](./MOD-28.py.yaml) | 種類のスキーマの `$ref` の解決と、`records` の行のスキーマ。 |
| [索引のサーバー / 文書のストア / store.py](./MOD-29.py.yaml) | 文書のキャッシュ・ID の引き当て・種類のスキーマ・文書の場所と、メタデータのずれの確かめ。 |
| [索引のサーバー / 文書のストア / types.py](./MOD-30.py.yaml) | 文書・読み込みの誤りと結果・同期のずれ・エイリアスの型。 |
| [索引のサーバー / 履歴 / query.py](./MOD-31.py.yaml) | git によるリビジョンの解決・一覧・変わったファイル・ファイルの日時・ワークツリーの一覧。 |
| [索引のサーバー / 履歴 / snapshot.py](./MOD-32.py.yaml) | リビジョンの書き出し。 |
| [索引のサーバー / 履歴 / types.py](./MOD-33.py.yaml) | リビジョン・変わったファイル・ファイルの日時・commit・ワークツリーの型。 |
| [索引のサーバー / 再起動と更新 / control.py](./MOD-34.py.yaml) | 再起動の要求を受けて uvicorn を止め、止まった後に `run_serve` が同じプロセスを置き換えるかを持つ。 |
| [索引のサーバー / 再起動と更新 / types.py](./MOD-35.py.yaml) | 管理の MCP の `restart`・`update` の結果の型と定数。 |
| [索引のサーバー / 再起動と更新 / update.py](./MOD-36.py.yaml) | 端末の設定の `clone` を `git pull --ff-only`・`uv sync` で更新し、新しいコードで移し替えの要否を確かめて、要らなければ再起動を要求する。 |
| [索引のサーバー / 設定の移し替え / service.py](./MOD-37.py.yaml) | `project-index migrate` の対象を決め、当てる手順を求め、バックアップを取ってから 1 回だけ書き込む。動いているサーバーには反映しない。 |
| [索引のサーバー / 設定の移し替え / steps.py](./MOD-38.py.yaml) | パッケージに入れた移し替えの手順を読み、メモリの上の YAML に 1 つずつ当てる。ファイルには書かない。 |
| [索引のサーバー / 設定の移し替え / types.py](./MOD-39.py.yaml) | `project-index migrate` の手順・対象・例外の型と終了コード。 |
| [索引のサーバー / プロンプトの文書の変換 / cli.py](./MOD-40.py.yaml) | `project-index prompt-doc` の処理。標準入力を変換して標準出力に出し、失敗を終了コードにする。 |
| [索引のサーバー / プロンプトの文書の変換 / markdown.py](./MOD-41.py.yaml) | プロンプトの YAML を読み、変数の表・テンプレート・例の組のセクションを持つ mdmark の Markdown にする。 |
| [索引のサーバー / プロンプトの文書の変換 / render.py](./MOD-42.py.yaml) | プロンプトの部品を Jinja2 で描画する。変数の値にパスを持たせて描画し、描画結果の値を区切りで囲む。 |
| [索引のサーバー / プロンプトの文書の変換 / runtime.py](./MOD-43.py.yaml) | サーバーが起動のときに `content/prompts/` のプロンプトの YAML を読んで検査し、MCP の instructions・ツールの description を描画する。画面用のマーカーは付けない。 |
| [索引のサーバー / プロンプトの文書の変換 / types.py](./MOD-44.py.yaml) | `project-index prompt-doc` が読むプロンプトの YAML のモデルと、描画の結果・例外の型。モデルは変換に使うキーだけを持ち、他のキーは読み捨てる。サーバーが起動のときに読むプロンプトの違反の型も持つ。 |
| [索引のサーバー / 関連 / graph.py](./MOD-45.py.yaml) | 関連の取り出しとたどり。 |
| [索引のサーバー / 関連 / render.py](./MOD-46.py.yaml) | `trace_related` の結果の Markdown。 |
| [索引のサーバー / 関連 / service.py](./MOD-47.py.yaml) | `trace_related` の関連のたどりと関連の候補。 |
| [索引のサーバー / 関連 / suggest.py](./MOD-48.py.yaml) | 関連の候補の提案。 |
| [索引のサーバー / 関連 / types.py](./MOD-49.py.yaml) | `trace_related` の要求と結果の型。 |
| [索引のサーバー / 検索 / body_parts.py](./MOD-50.py.yaml) | 本文の切り出し。 |
| [索引のサーバー / 検索 / cursor.py](./MOD-51.py.yaml) | 続きのカーソルの作成と解読。 |
| [索引のサーバー / 検索 / fields.py](./MOD-52.py.yaml) | 項目の値・計算項目・使える項目・見出しの行。 |
| [索引のサーバー / 検索 / filters.py](./MOD-53.py.yaml) | 条件の木の確かめと照合・語の照合・正規表現・比べる値の解釈。 |
| [索引のサーバー / 検索 / render.py](./MOD-54.py.yaml) | `search_docs` の結果の Markdown。 |
| [索引のサーバー / 検索 / service.py](./MOD-55.py.yaml) | `search_docs` の条件の木・並べ替え・集計・量の上限。 |
| [索引のサーバー / 検索 / snippets.py](./MOD-56.py.yaml) | 行の分割・抜粋の検索・当たった行の数・一致した箇所の抜き出し。 |
| [索引のサーバー / 検索 / terms.py](./MOD-57.py.yaml) | 用語の一覧と、その Markdown。 |
| [索引のサーバー / 検索 / types.py](./MOD-58.py.yaml) | `search_docs`・用語の一覧の要求と結果の型。 |
| [索引のサーバー / 会話の記録 / store.py](./MOD-59.py.yaml) | 会話キーごとの返し済み・前回読んだ内容・閲覧と編集の SQLite への記録と読み出し。 |
| [索引のサーバー / 会話の記録 / types.py](./MOD-60.py.yaml) | 会話の記録の会話キー・前回読んだ内容・閲覧と編集の記録の型。 |
| [索引のサーバー / セッションの開始 / route.py](./MOD-61.py.yaml) | `POST /_admin/session-start` のルート。読み取り API のスキーマ（`/_api/openapi.json`）に載せない。 |
| [索引のサーバー / セッションの開始 / service.py](./MOD-62.py.yaml) | `/clear`・圧縮の後に、その会話の返し済みの記録を削除する。 |
| [索引のサーバー / セッションの開始 / types.py](./MOD-63.py.yaml) | `POST /_admin/session-start` の本文と応答の型と、返し済みの記録を削除する理由。 |
| [索引のサーバー / 端末の設定 / query.py](./MOD-64.py.yaml) | 端末の設定の場所・読み込みと検証・待ち受けのポート。 |
| [索引のサーバー / 端末の設定 / route.py](./MOD-65.py.yaml) | 端末の設定のルーター（`GET`・`PUT`・`POST /settings/sources`）。 |
| [索引のサーバー / 端末の設定 / service.py](./MOD-66.py.yaml) | `sources[]` の保存。 |
| [索引のサーバー / 端末の設定 / types.py](./MOD-67.py.yaml) | 端末の設定と、端末の設定の API の `sources[]` の要求と結果の型。 |
| [索引のサーバー / 配信元 / merge.py](./MOD-68.py.yaml) | 設定の YAML のマージ。 |
| [索引のサーバー / 配信元 / registry.py](./MOD-69.py.yaml) | 配信する配信元の一覧と読み直し。 |
| [索引のサーバー / 配信元 / service.py](./MOD-70.py.yaml) | 配信元の設定の読み込みと検証、スクリプトとバージョンの確かめ。 |
| [索引のサーバー / 配信元 / types.py](./MOD-71.py.yaml) | 配信元の設定・文書の行・スクリプト・配信中の配信元・状態の型。 |
| [索引のサーバー / 検査 / markdown.py](./MOD-72.py.yaml) | スキーマで Markdown と宣言したキーのうち操作で変えた値を mdmark の点検に通し、描画時の書き方の警告を違反にする。 |
| [索引のサーバー / 検査 / rules.py](./MOD-73.py.yaml) | スキーマ・ID の形・関連の種類の検査。 |
| [索引のサーバー / 検査 / scripts.py](./MOD-74.py.yaml) | `validators[]` の出力の解釈。 |
| [索引のサーバー / 検査 / service.py](./MOD-75.py.yaml) | 検査をまとめて通す処理と、読み取りの結果のキャッシュ。 |
| [索引のサーバー / 読み取り API / nav.py](./MOD-76.py.yaml) | `nav` の `auto` の当たる文書の数・`filter` の検証・警告（管理の MCP と配信元の説明が使う）。タブとサイドバーの組み立ては dev-docs の画面のサーバーが持つ。 |
| [索引のサーバー / 読み取り API / paths.py](./MOD-77.py.yaml) | 文書のページのパスと、読み取り API が読む場所。 |
| [索引のサーバー / 読み取り API / search.py](./MOD-78.py.yaml) | 語での検索。 |
| [索引のサーバー / 読み取り API / types.py](./MOD-79.py.yaml) | 読み取り API の要求と応答のデータモデル。 |
| [索引のサーバー / 書き込み / apply.py](./MOD-80.py.yaml) | 項目の操作の適用と、共通のキーの列名への読み替え。 |
| [索引のサーバー / 書き込み / ids.py](./MOD-81.py.yaml) | `ids.format` からの ID の生成。 |
| [索引のサーバー / 書き込み / locks.py](./MOD-82.py.yaml) | 配信元ごとの書き込みの排他。 |
| [索引のサーバー / 書き込み / placement.py](./MOD-83.py.yaml) | 新しい文書の置き場所。 |
| [索引のサーバー / 書き込み / service.py](./MOD-84.py.yaml) | `write_docs`・`delete_docs` の操作の適用・検査・書き換えと、バージョンの確かめ。 |
| [索引のサーバー / 書き込み / types.py](./MOD-85.py.yaml) | `write_docs`・`delete_docs` の要求と結果の型。 |
| [索引のサーバー / 履歴 / git.py](./MOD-86.py.yaml) | git の実行と、リポジトリの直下の解決。 |
| [索引のサーバー / スクリプトの実行 / mdmark.py](./MOD-87.py.yaml) | mdmark の CLI の `check --text -` で Markdown の文字列を点検し、出力をずれの並びにする。 |
| [索引のサーバー / スクリプトの実行 / scripts.py](./MOD-88.py.yaml) | `validators[]`・`converters[]`・`generators[]` のスクリプトの制限時間つきの実行と、実行できるかの確かめ。 |
| [索引のサーバー / 起動 / main.py](./MOD-89.py.yaml) | `project-index serve`・`project-index migrate` の部品の配線と、配信元の読み直し。 |
| [索引のサーバー / 起動 / app.py](./MOD-90.py.yaml) | ルートと MCP のマウントをまとめたアプリの組み立て。 |
| [索引のサーバー / 起動 / error_handlers.py](./MOD-91.py.yaml) | 例外の problem+json への変換。 |
| [索引のサーバー / 起動 / lifespan.py](./MOD-92.py.yaml) | MCP のセッションの管理と、記録の削除。 |
| [索引のサーバー / 文書のMCP / admin.py](./MOD-93.py.yaml) | 管理の MCP の組み立て（ツールの登録）。 |
| [索引のサーバー / 文書のMCP / docs.py](./MOD-94.py.yaml) | 文書の MCP の組み立て（ツールの登録）。 |
| [索引のサーバー / 文書のMCP / result.py](./MOD-95.py.yaml) | ツールの結果・エラーの変換と、2 つの MCP のツール名とプロンプトの ID。 |
| [索引のサーバー / 共通 / origin.py](./MOD-96.py.yaml) | 端末の設定の API への、ブラウザからの別のオリジンの書き込みの確認。 |
| [索引のサーバー / 共通 / api_model.py](./MOD-97.py.yaml) | 読み取り API の DTO の基底（キーは camelCase）。 |
| [索引のサーバー / 共通 / errors.py](./MOD-98.py.yaml) | `ProjectIndexError` と、MCP・読み取り API が返すエラーの階層。 |
| [索引のサーバー / 共通 / files.py](./MOD-99.py.yaml) | 一時ファイルからのファイルの置き換え。 |
| [索引のサーバー / 共通 / hashing.py](./MOD-100.py.yaml) | 内容のハッシュ（文書のバージョン）。 |
| [索引のサーバー / 共通 / paths.py](./MOD-101.py.yaml) | 作業場所の glob の照合とパスの正規化。 |
| [索引のサーバー / 共通 / schema_check.py](./MOD-102.py.yaml) | JSON Schema の違反を、項目のパスつきの `Violation` にする。 |
| [索引のサーバー / 共通 / version.py](./MOD-103.py.yaml) | 動いているプロセスが起動した時点の project-index のバージョン。 |
| [索引のサーバー / 共通 / yaml_io.py](./MOD-104.py.yaml) | YAML の読み込みと、往復編集の読み書き。 |
| [索引のサーバー / スクリプトの実行](./MOD-105.yaml) | 配信元の設定の `validators[]`・`converters[]`・`generators[]` のコマンドを、配信元の直下で子プロセスとして制限時間つきで動かす。 |
| [索引のサーバー / 会話の記録](./MOD-106.yaml) | 会話キー（`session_id`・`agent_id`）ごとに、返した文書の ID とバージョン・本文を返した時点の内容・閲覧と編集を `state_dir` の SQLite に記録する。 |
| [索引のサーバー / 入口](./MOD-107.yaml) | `project-index` コマンドの入口。引数を読み、バージョン・ヘルプを出すか、サブコマンドの処理へ渡す。 |
| [索引のサーバー / 共通](./MOD-108.yaml) | どの分類からも使う例外の階層・YAML の読み書き・内容のハッシュ・パスの照合と、端末の設定の API への書き込みの要求のオリジンの確認。 |
| [索引のサーバー / 変換](./MOD-109.yaml) | `converters[]` を指す種類の文書を、配信元のスクリプトで Markdown にし、結果を控える。 |
| [索引のサーバー / 変更](./MOD-110.yaml) | `list_changes` の処理。区間（commit・日時・ブランチ・タグ）か、この会話で前回読んだ時点から今までに変わった文書・変わったキー・差分の行を返す。 |
| [索引のサーバー / 履歴](./MOD-111.yaml) | git を子プロセスで呼び、リビジョン（ブランチ・タグ・commit・日時）の解決・一覧・変わったファイル・ファイルの日時を返す。 |
| [索引のサーバー / 文書のMCP](./MOD-112.yaml) | 文書の MCP（`/mcp`）と管理の MCP（`/_admin/mcp`）の組み立て。 |
| [索引のサーバー / 文書のストア](./MOD-113.yaml) | 配信元の `documents[]` の行ごとにファイルを集め、ファイルか `records` の要素を 1 件の文書にして、メタデータ・バージョン・日時を付けて返す。 |
| [索引のサーバー / 書き込み](./MOD-114.yaml) | `write_docs`・`delete_docs` の処理。操作を全て当てた後の文書を検査に通し、通ったときだけ作業ツリー（Git 管理外の配信元はそのフォルダ）のファイルを書き換える。 |
| [索引のサーバー / 検査](./MOD-115.yaml) | 文書を種類のスキーマ・`ids.format`・`related.types`・配信元の `validators[]` で検査し、違反の並びを返す。 |
| [索引のサーバー / 検索](./MOD-116.yaml) | `search_docs` の処理。条件の木で文書を絞り、並べ替え・集計・量の上限をかけて、指定した項目だけを返す。 |
| [索引のサーバー / 権限と作業場所](./MOD-117.yaml) | 作業場所（`cwd`）と配信元の `scope` を照らして使える配信元と権限を決め、MCP の引数（`source`・`ref`・`worktree`）から読み書きする場所を解く。 |
| [索引のサーバー / 端末の設定](./MOD-118.yaml) | 端末の設定 `settings.yaml` をスキーマで検証して読み、端末の設定の API に送られた `sources[]` を、他のキーとコメントを保って書き換える。 |
| [索引のサーバー / 説明](./MOD-119.yaml) | `describe` の処理。引数の数で、今の作業場所から使える配信元の一覧・配信元の説明書と種類の一覧・種類のスキーマを返す。 |
| [索引のサーバー / 起動](./MOD-120.yaml) | `project-index serve` と `project-index migrate` の処理。端末の設定と配信元を読み、部品を配線して、読み取り API・文書の MCP・管理の MCP・セッションの開始を 1 つのアプリとして待ち受ける。 |
| [索引のサーバー / 配信元](./MOD-121.yaml) | 端末の設定の `sources[]` の行ごとに、配信元の設定の YAML をマージして検証し、配信する配信元の一覧を作る。 |
| [索引のサーバー / 関連](./MOD-122.yaml) | `trace_related` の処理。起点の文書かコードのパスから、メタデータの `related` を深さと向きの指定でたどる。 |
| [索引のサーバー / 書き込み / hints.py](./MOD-123.py.yaml) | `write_docs` のスキーマの違反に、違反した項目のスキーマの説明を添える。 |
| [索引のサーバー / 配信元 / schema_ref.py](./MOD-124.py.yaml) | `documents[].schema` でほかの配信元のリビジョンのスキーマを指す参照の型と、その読み取り。 |
| [索引のサーバー / 読み取り API / service.py](./MOD-125.py.yaml) | 読み取り API の配信元の設定・文書の一覧・文書の取得・検討事項の取得。 |
| [索引のサーバー / 読み取り API / route.py](./MOD-126.py.yaml) | 読み取り API のルーター（`/sources` の下）。 |
| [索引のサーバー / 読み取り API](./MOD-127.yaml) | dev-docs の画面のサーバーなどが呼ぶ読み取り API（配信元の一覧と状態・配信元の設定・文書の一覧と取得・検討事項・語での検索・リビジョンの一覧）。 |

<!-- /table -->

# interface

操作ごとの入出力・制約・正常系と異常系のフロー（結合テストの元）

## 目次

<!-- table: data -->

| ページ | 概要 |
| --- | --- |
| [配信元の説明](./IF-1.yaml) | 配信元の説明（describe） |
| [文書の検索](./IF-2.yaml) | 文書の検索（search_docs） |
| [関連のたどり](./IF-3.yaml) | 関連のたどり（trace_related） |
| [変更の一覧](./IF-4.yaml) | 変更の一覧（list_changes） |
| [用語の一覧](./IF-5.yaml) | 用語の一覧（list_match_words） |
| [文書の書き込み](./IF-6.yaml) | 文書の書き込み（write_docs） |
| [文書の削除](./IF-7.yaml) | 文書の削除（delete_docs） |
| [状態の取得](./IF-8.yaml) | 状態の取得（status） |
| [設定の読み直し](./IF-9.yaml) | 設定の読み直し（reload） |
| [再起動](./IF-10.yaml) | 再起動（restart） |
| [更新](./IF-11.yaml) | 更新（update） |
| [配信元の検査](./IF-12.yaml) | 配信元の検査（check_project） |
| [試しの変換](./IF-13.yaml) | 試しの変換（try_convert） |
| [画面の構成の書き込み](./IF-14.yaml) | 画面の構成の書き込み（write_nav） |
| [起動](./IF-15.yaml) | 起動（project-index serve（CLI）） |
| [設定の移し替え](./IF-16.yaml) | 設定の移し替え（project-index migrate（CLI）） |
| [載せるファイルの一覧](./IF-17.yaml) | 載せるファイルの一覧（project-index files（CLI）） |
| [プロンプトの文書の変換](./IF-18.yaml) | プロンプトの文書の変換（project-index prompt-doc（CLI）） |
| [セッション開始のフック](./IF-19.yaml) | セッション開始のフック（Claude Code の SessionStart（startup・resume・clear・compact・fork）） |
| [ツール実行前のフック](./IF-20.yaml) | ツール実行前のフック（Claude Code の PreToolUse（matcher mcp__plugin_project-index_project-index__.*）） |
| [セッションの開始](./IF-21.yaml) | セッションの開始（POST /_admin/session-start） |
| [配信元の一覧と状態](./IF-22.yaml) | 配信元の一覧と状態（GET /sources） |
| [配信元の設定の取得](./IF-23.yaml) | 配信元の設定の取得（GET /sources/{source}/config） |
| [文書の一覧](./IF-24.yaml) | 文書の一覧（GET /sources/{source}/docs） |
| [文書の取得](./IF-25.yaml) | 文書の取得（GET /sources/{source}/docs/{path}） |
| [検討事項の ID の一覧](./IF-26.yaml) | 検討事項の ID の一覧（GET /sources/{source}/decisions） |
| [検討事項の文書の取得](./IF-27.yaml) | 検討事項の文書の取得（GET /sources/{source}/decisions/{id}） |
| [語での検索](./IF-28.yaml) | 語での検索（GET /sources/{source}/search） |
| [リビジョンの一覧](./IF-29.yaml) | リビジョンの一覧（GET /sources/{source}/refs） |
| [端末の設定の取得](./IF-30.yaml) | 端末の設定の取得（GET /settings/sources） |
| [端末の設定の保存](./IF-31.yaml) | 端末の設定の保存（PUT /settings/sources） |
| [端末の設定の配信元の 1 行の追加](./IF-32.yaml) | 端末の設定の配信元の 1 行の追加（POST /settings/sources） |
| [端末の設定の配信元の 1 行の変更](./IF-33.yaml) | 端末の設定の配信元の 1 行の変更（PATCH /settings/sources/{id}） |
| [端末の設定の配信元の 1 行の削除](./IF-34.yaml) | 端末の設定の配信元の 1 行の削除（DELETE /settings/sources/{id}） |

<!-- /table -->

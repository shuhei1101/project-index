# scenario

単一 / 複合ユースケースの業務フロー設計（E2E テストの元）

## 目次

<!-- table: data -->

| ページ | 概要 |
| --- | --- |
| [project-indexで配信元の文書を読み書きする](./SC-1.yaml) | project-index を入れて配信元を登録し、文書を文書の MCP と読み取り API で読み書きするまでの流れ |
| [project-indexを入れる](./SC-2.yaml) | `/project-index:global-setup` の端末の設定・env の用意と、2 回目以降のバージョンの確認 |
| [project-indexを更新する](./SC-3.yaml) | `update` での更新と `project-index migrate` での端末の設定の移し替え |
| [起動する](./SC-4.yaml) | `project-index serve` の待ち受けと配信元ごとの起動時の検証、SessionStart のフックでの起動 |
| [配信元を追加する](./SC-5.yaml) | `/project-index:setup` での配信元の登録と、2 回目以降の管理用の YAML の突き合わせ |
| [エージェントが調べる](./SC-6.yaml) | `describe`・`search_docs`・`trace_related` と、権限・ワークツリー・横断検索・1 セッション 1 回 |
| [エージェントが書き込む](./SC-7.yaml) | `write_docs`・`delete_docs` と、検査・書き込む作業ツリー・参照されている文書の削除 |
| [変更をレビューする](./SC-8.yaml) | `list_changes` の区間の解決と変わった文書・差分の行 |
| [YAMLを直接編集した](./SC-9.yaml) | 直接編集した YAML の読み直しと、読んだ後に変わった文書への書き込み |
| [設定・スクリプトを変える](./SC-10.yaml) | `check_project`・`try_convert` での確認と `reload` での反映 |
| [画面のサーバーが文書を読む](./SC-11.yaml) | 読み取り API での配信元の一覧・配信元の設定・文書の一覧・文書・検討事項の文書・検索・リビジョンの一覧の取得 |
| [端末の設定の配信元を変える](./SC-12.yaml) | 端末の設定の API での配信元の取得と、追加・停止・削除した後の保存・1 行の追加 |

<!-- /table -->

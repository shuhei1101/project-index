# 管理用の YAML に、書き込みの API のファイルとテスト 8 件の行を追加する

## 概要

書き込みの API のファイルとテスト 8 件が、開発ドキュメントのタブ「コード」に並び、`search_docs` でメタデータから探せるようになる。

## 背景

[Issue #304](https://github.com/shuhei1101/project-index/issues/304) の要望。
管理の MCP の `check_project` が「索引の同期: 管理用の YAML に無いファイル 8 件」を返す。
8 件は [#210](https://github.com/shuhei1101/project-index/pull/210) などで追加したファイルで、[src/files.yaml](https://github.com/shuhei1101/project-index/blob/d01cc35033050686d7e50b6e2ecc379186411544/src/files.yaml)・[tests/files.yaml](https://github.com/shuhei1101/project-index/blob/d01cc35033050686d7e50b6e2ecc379186411544/tests/files.yaml) に行が無い。
[#303](https://github.com/shuhei1101/project-index/pull/303) の作業中に気づき、スコープ外へ回した。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理と影響する UC・更新ドキュメント・スコープ外 |
| [タスク一覧](./tasks.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.mark.md) | 管理用の YAML の行の計画書 |

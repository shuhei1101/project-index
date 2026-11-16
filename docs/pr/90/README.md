# コミットできないリポジトリを配信元にできるようにする（端末の設定で disk を指定し、*.local.* のファイルで運用する）

## 概要

利用者が、project-index のために追加するファイルを 1 つもコミットせずに、Git のリポジトリを配信元にし、そのリポジトリの中と外部の作業場所・dev-docs の画面から索引と検索を使用できるようにする。

## 背景

[Issue #87](https://github.com/shuhei1101/project-index/issues/87) の要望。
会社のリポジトリのように `project-index.yaml`・管理用の YAML・スキーマをコミットできないリポジトリでは、Git のリポジトリの配信元が `default_ref` のリビジョンから参照するため、スキーマ・スクリプト・文書が見つからず配信できない。
Git のリポジトリかどうかは配信元のフォルダが Git の作業ツリーの中かで自動で決まり（[sources/service.py](https://github.com/shuhei1101/project-index/blob/006a49034a210dfb1eb2f8b998abad760c002f5b/src/project_index/features/sources/service.py#L571) の `is_git=top is not None`）、設定で変えられない。
書き込みの先もワークツリーだけで、クローン本体で作業するリポジトリでは管理用の YAML を書き込めない。

dev-docs の画面の側の対応は [shuhei1101/dev-docs#235](https://github.com/shuhei1101/dev-docs/issues/235) が持ち、この PR の後に着手する。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |
| [プラグイン](./プラグイン.md) | プラグインの計画書 |

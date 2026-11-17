# 管理用の YAML に無いファイルの判定・worktree を指定した読み取り・setup の初回の索引の同期を修正する

## 概要

利用者が配信元の直下の管理用の YAML に直下のファイルだけを記載でき、setup の初回の後に索引の同期の件数が 0 になる。
エージェントが `worktree` を指定した読み取りで、そのワークツリーの `project-index.yaml` に加えた行の文書を参照できる。

## 背景

束の親 [Issue #140](https://github.com/shuhei1101/project-index/issues/140) の要望で、次の 3 件の子 Issue をまとめて扱う。

| 子 | 切り出し元 |
| --- | --- |
| [#133](https://github.com/shuhei1101/project-index/issues/133) | 作業 PR [#132](https://github.com/shuhei1101/project-index/pull/132) で、project-index 自身の配信元の直下の 10 件と `docs/` 直下の 2 件を管理用の YAML に記載できなかった（[確認事項](https://github.com/shuhei1101/project-index/pull/132#discussion_r4596998841)の推奨案 A） |
| [#134](https://github.com/shuhei1101/project-index/issues/134) | 作業 PR [#132](https://github.com/shuhei1101/project-index/pull/132) で、`search_docs` がワークツリーに加えた行の文書を返却せず、`write_docs` で書き換えられなかった |
| [#135](https://github.com/shuhei1101/project-index/issues/135) | 作業 PR [#131](https://github.com/shuhei1101/project-index/pull/131) の reviewer の[対象外の逸脱の報告](https://github.com/shuhei1101/project-index/pull/131#discussion_r4597257369) |

作業 PR [#131](https://github.com/shuhei1101/project-index/pull/131) で、「管理用の YAML に無いファイル」の判定は、ほかの有効な `documents` の行の `paths` に該当するファイルを数えなくなった。
残るのは、より深いフォルダの管理用の YAML が本文に持つファイル・どの行の文書でもないフォルダ（`docs/pr/` など）・setup が初回に作るファイルと、`worktree` を指定した読み取りの配信元の作り方。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 管理用の YAML に無いファイルの判定・`project-index files`・`worktree` を指定した読み取りの計画書 |
| [プラグイン](./プラグイン.md) | setup のスキルの計画書 |

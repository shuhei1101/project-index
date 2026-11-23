# SKILL.md の自動生成（project-index skill-md）を廃止する

## 概要

`project-index skill-md`（SKILL.md の生成と `--check` の検査）とその設計書・テスト・配信元の設定の登録を削除し、SKILL.md を設計書を見ながら手で記載するファイルにする。

## 背景

[Issue #261](https://github.com/shuhei1101/project-index/issues/261) の要望。[#243](https://github.com/shuhei1101/project-index/pull/243) で `docs/agent-flow/` の `type: skill` のエージェントフローから SKILL.md を組み立てる `project-index skill-md` が入り、`project-index.yaml` の `generators[]`・`validators[]` に登録された。ユーザーの判断（[shuhei1101/knowledge#544 のコメント](https://github.com/shuhei1101/knowledge/pull/544#issuecomment-7074367837)）で、SKILL.md は設計書から生成せず、設計書と SKILL.md を二重管理して食い違いをレビューで確認することになった。`project-index skill-md` はタグ v0.2.0 に含まれず未リリース。

## 計画書

<!-- table: {"kind": "data"} -->

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |
| [プラグイン](./プラグイン.mark.md) | プラグインの計画書 |

<!-- /table -->

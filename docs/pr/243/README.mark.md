# type: skill のエージェントフローから SKILL.md を生成するコマンドを追加し、generators に登録する

## 概要

開発者が `docs/agent-flow/` の `type: skill` のエージェントフローを書き換えると、`skill.path` の SKILL.md がエージェントフローから生成され、SKILL.md を手で修正せずに済むようにする。

## 背景

[Issue #241](https://github.com/shuhei1101/project-index/issues/241) の要望（依頼元 [#239](https://github.com/shuhei1101/project-index/pull/239) のスコープ外の行）。
#239 でスキル global-setup・setup・feedback の設計書を `docs/agent-flow/skill-*.yaml` として作成したが、このリポジトリには SKILL.md の生成の仕組みが無く、`plugins/project-index/skills/*/SKILL.md` を手でエージェントフローに合わせた。
エージェントフローと SKILL.md を両方手で修正する必要があり、食い違いが起きうる。
knowledge には同じ生成のインターフェース定義（IF-312-1『SKILL.md の生成』、`docs/skill/` が対象）がある。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 生成のコマンドと generators への登録の計画書 |
| [プラグイン](./プラグイン.mark.md) | SKILL.md の生成物への置き換えの計画書 |

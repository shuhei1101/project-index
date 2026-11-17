# setup がプロンプトの行を記載するとき、content/prompts/ の YAML を管理用の YAML の行に記載せず 1 つの文書として配信する

## 概要

利用者が `/project-index:setup` で `content/prompts/` を持つフォルダを配信元にしたとき、プロンプトの YAML が 1 つの文書として配信される。

## 背景

[Issue #124](https://github.com/shuhei1101/project-index/issues/124) の要望。
作業 PR [#123](https://github.com/shuhei1101/project-index/pull/123)（起点 Issue [#115](https://github.com/shuhei1101/project-index/issues/115)）の reviewer の[対象外の逸脱の報告](https://github.com/shuhei1101/project-index/pull/123#discussion_r4596435055)から切り出した。

setup の手順 3 で範囲を既定の `**/*` にすると、手順 4 の `project-index files` は `content/prompts/` の YAML も管理用の YAML の行の候補に入れる。
同じ手順 4 でプロンプトの `documents` の行も候補に加わり、手順 5 で両方を記載するため、同じファイルが 2 つの文書として配信される。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [プラグイン](./プラグイン.md) | setup のスキルの計画書 |
| [索引のサーバー](./索引のサーバー.md) | 索引の同期の数え方と `project-index files` の計画書 |

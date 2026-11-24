# dev-docs のメタデータの画面から直コミットしてよい種類を project-index.yaml の direct_commit に追加する

## 概要

利用者が dev-docs のメタデータの画面（タグ・用語集・管理用の YAML の説明など）から、project-index の文書を develop へ直コミットできるようになる。

## 背景

[#283](https://github.com/shuhei1101/project-index/issues/283) の要望。
依頼元は [shuhei1101/dev-docs#314](https://github.com/shuhei1101/dev-docs/issues/314)（作業 PR [shuhei1101/dev-docs#317](https://github.com/shuhei1101/dev-docs/pull/317) のスコープ外の行）。
project-index の配信元の設定（[project-index.yaml](https://github.com/shuhei1101/project-index/blob/develop/project-index.yaml)）に `direct_commit` が無いため、画面では全ての種類が参照のみになる。
dev-docs 自身は [shuhei1101/dev-docs#317](https://github.com/shuhei1101/dev-docs/pull/317) で `direct_commit: {branch: develop, kinds: [...]}` を追加し、管理用の YAML の種類を本文を書き換えない（`body: false`）行として許可した。
同じ内容の aituber 側の Issue は [shuhei1101/aituber#222](https://github.com/shuhei1101/aituber/issues/222)。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |

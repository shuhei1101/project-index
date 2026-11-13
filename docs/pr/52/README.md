# 配信元の設定の取得（IF-23）の応答の例の github のキーを、実装の issueLabels に合わせる

## 概要

配信元の設定の取得（IF-23）の応答の例の `github` のキーを、実装が返却する `issueLabels` に合わせる。

## 背景

[Issue #51](https://github.com/shuhei1101/project-index/issues/51) の要望。
`docs/interface/IF-23.yaml` の `response_example` は `github` を `{"repository": ..., "labels": [...]}` と記載しているが、実装の `GitHubTarget` は `issue_labels` を camelCase にした `issueLabels` で返却し、使う側（[shuhei1101/dev-docs#183](https://github.com/shuhei1101/dev-docs/pull/183)）も `issueLabels` で読む。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

# 読み取り API の文書の一覧と文書の取得に、resolve_metadata で解決した共通のキーを返却する

## 概要

dev-docs の画面のサーバーが、エイリアスの集めと `nav` の `filter` に使用する共通のキーを、自分で組み立てずに読み取り API から受け取れるようにする。

## 背景

[Issue #53](https://github.com/shuhei1101/project-index/issues/53) の要望。
文書の一覧（IF-24）と文書の取得（IF-25）の `metadata` は、共通のキーのうち `name`・`description`・`tags`・`visibility` だけを返却する。
[shuhei1101/dev-docs#183](https://github.com/shuhei1101/dev-docs/pull/183) では、配信元の設定の取得の `documents[].metadata`・`alias_type` と文書の一覧の `value` から、`resolve_metadata` と同じ規則で dev-docs の側で組み立てている。
同じ規則を 2 つのリポジトリが持つため、`METADATA_KEYS` が project-index だけで増えると食い違う。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

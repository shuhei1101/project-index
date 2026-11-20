# 負荷の高い間でも、文書の取得の読み取り API で文書 1 件の取得が待たされないようにする

## 概要

dev-docs の画面のサーバーが読み取り API の文書の取得（`GET /sources/{source}/docs/{path}`）で文書 1 件を取得するとき、端末の負荷が高い間でも待たされずに返るようにする。

## 背景

[Issue #215](https://github.com/shuhei1101/project-index/issues/215) の不具合（依頼元は [shuhei1101/dev-docs#301](https://github.com/shuhei1101/dev-docs/issues/301)）。
ロードアベレージが 8 コアで 15 の間に、dev-docs の画面から ai-monitor の文書 `docs/data/DATA-3694-1.yaml` を差分つきで開くと、文書 1 件の取得に約 7.8 秒かかった（応答は約 744KB）。
dev-docs 側は [shuhei1101/dev-docs#302](https://github.com/shuhei1101/dev-docs/pull/302) で文書の一覧の保持と gzip の応答を入れたが、文書 1 件の取得は project-index の処理時間のため縮まらない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

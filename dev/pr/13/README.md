# dev/ を廃止して文書を docs/ 1 つにまとめ、ai-monitor#3307 と同じ構成へ移す

## 概要

`dev/` を廃止し、このリポジトリの文書を `docs/` の種類ごとのフォルダと `schemas/` へまとめ、公開範囲を各文書のメタデータ `visibility` で持つ。

## 背景

[Issue #12](https://github.com/shuhei1101/project-index/issues/12) の要望。
[shuhei1101/ai-monitor#3307](https://github.com/shuhei1101/ai-monitor/pull/3307) が AI Monitor 自身の文書を `docs/` 1 つへ移し、全ての監視対象のプロジェクトも同じ構成へ移す要件を持つ（[確認ログの決着](https://github.com/shuhei1101/ai-monitor/pull/3307#discussion_r4506279520)）。
この PR はレビューに合格した後もマージせず、ai-monitor#3307 のマージの後に、#3307 の反映作業『監視対象のプロジェクトの移行の PR のマージ』で ai-monitor の planner がマージする（[マージ提案のレビュー](https://github.com/shuhei1101/ai-monitor/pull/3307#discussion_r4512361704)）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの設計書・Schema・設定の移し替えの計画書 |
| [プラグイン](./プラグイン.md) | プラグインの設計書の移し替えの計画書 |

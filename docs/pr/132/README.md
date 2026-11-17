# project-index 自身の配信元の検索の対象とメタデータを見直し、「読み直し」の文言を「再読み込み」に統一する

## 概要

project-index 自身の配信元の検索の対象とメタデータを #101・#102 の付け方に合わせ、ほかの配信元の見直しをそれぞれのリポジトリの Issue に分ける。
設計書・公開ドキュメント・コード・テストの「読み直し」「読み直す」を「再読み込み」に統一する。

## 背景

[Issue #130](https://github.com/shuhei1101/project-index/issues/130) の要望で、同じタグ（`kind:文書の書き換え`・`scope:docs`）の計画の行 [#104](https://github.com/shuhei1101/project-index/issues/104)・[#71](https://github.com/shuhei1101/project-index/issues/71) を 1 つの作業 PR で対応する。

- #104: setup の付け方（[#101](https://github.com/shuhei1101/project-index/issues/101)）と推奨の範囲（[#102](https://github.com/shuhei1101/project-index/issues/102)）が develop へ入った。既存の配信元の検索の対象とメタデータは、それより前の付け方のまま
- #71: [PR #70](https://github.com/shuhei1101/project-index/pull/70) で設定の反映の値を「再読み込み」にした後も、同じ動作を説明する「読み直し」「読み直す」が残っている

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |
| [プラグイン](./プラグイン.md) | プラグインの計画書 |

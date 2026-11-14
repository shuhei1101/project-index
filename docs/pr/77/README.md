# PR ドキュメントの dev/pr/13/ を docs/pr/13/ へ移し、dev/ フォルダを削除する

## 概要

作業 PR #13 の PR ドキュメント `dev/pr/13/` を `docs/pr/13/` へ移し、`dev/` フォルダとフォルダ構成の設計書の `dev` のエントリを削除する。

## 背景

[Issue #74](https://github.com/shuhei1101/project-index/issues/74) の要望。
PR ドキュメントが `dev/pr/13/`（作業 PR #13 の 1 件）と `docs/pr/` の 2 か所に分かれていて、`dev/` には `dev/pr/13/` しかない。
[作業 PR #73](https://github.com/shuhei1101/project-index/pull/73) でフォルダ構成の設計書 `docs/layout/LAY-73-1.yaml` を作り、規約『フォルダ構成の切り方とレビュー』の観点「同じ種類が散る」に当たると分かった。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |

# AI Monitor v0.4.0 の配布物へ追従する

## 概要

取り込んだ AI Monitor の版の記録を v0.3.0 から v0.4.0 へ上げ、v0.4.0 で変わった規約・テンプレート・判定フローチャートと配布先の反映作業にこのリポジトリを合わせる。

## 背景

[Issue #79](https://github.com/shuhei1101/project-index/issues/79) は、AI Monitor が v0.4.0 の版上げで配った追従 Issue。
`ai-monitor-version.ini` は v0.3.0 のまま。
配布先の反映作業 8 件のうち、[ai-monitor#3430](https://github.com/shuhei1101/ai-monitor/pull/3430) の『各プロジェクトのスキーマの参照への移行』は task-planner の受付判断で [#76](https://github.com/shuhei1101/project-index/issues/76) へ移した。
残る 7 件は受付判断で「済み」「対象外」と判定しており、この PR で実行スクリプトを流して確かめ、記録する。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [反映作業](./反映作業/index.yaml) | 配布先の反映作業 7 件の一覧と、作業ごとのスクリプト・dry-run.log |

# test.yml の paths で pytest のノード ID（`{ファイル}::{関数}`）を受け付け、関数の単位で結合テストをランナーで回せるようにする

## 概要

開発者が、テスト実行方法の結合テスト（バック）の `run_runner` で、結合テストを関数の単位（pytest のノード ID）で指定してランナーで回せるようになる。

## 背景

[Issue #172](https://github.com/shuhei1101/project-index/issues/172) の要望。
[#169](https://github.com/shuhei1101/project-index/pull/169) の結合テスト作成で、`paths` に `tests/integration/server/test_write_docs.py::test_normal_when_text_edits_ref_path` を指定したところ、`.github/workflows/test.yml` の `paths` の検査が `:` を含む値を断った（[run 44116414260](https://github.com/shuhei1101/project-index/actions/runs/44116414260)）。
判定フローチャート『結合テストの実行範囲』の R7 は関数の単位で範囲を決定することがあり、今は手元の個別実行に逃がすしかない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | テストの全件実行の workflow とテスト実行方法の計画書 |

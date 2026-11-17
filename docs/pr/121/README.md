# develop の結合テストの fail を修正し、write_docs の書き出しで元のファイルの字下げを維持する

## 概要

develop の結合テストの全件実行で fail する 4 件を pass させ、`write_docs` で YAML の文書を書き換えたときに、変えた行だけが差分になるようにする。

## 背景

束の親 Issue [#120](https://github.com/shuhei1101/project-index/issues/120) の要望で、子は次の 2 件。

- [#117](https://github.com/shuhei1101/project-index/issues/117): develop（[72ad6fa](https://github.com/shuhei1101/project-index/commit/72ad6fadb49bc874b33e5ab33a7e5eec9da7a7e3)）で結合テストの全件を実行すると 3 件が fail する。作業 PR [#116](https://github.com/shuhei1101/project-index/pull/116) でランナーで実行したところ、ランナーでだけ fail する 1 件（`test_try_convert.py::test_error_when_invalid_config`）が追加で見つかった。#116 のランナーでの全件実行の前提になる
- [#118](https://github.com/shuhei1101/project-index/issues/118): `write_docs` で `docs/interface/index.yaml` の `items` に 1 行を追加すると、既存の全ての行の字下げが変わり、差分が 150 行になる。規約『既存文章の維持』の「差分は意図のある変更だけにする」に反する

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

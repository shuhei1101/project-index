# describe の単体テストの fixture の request.node に型を付け、pyright の reportUnknownMemberType を解消する

## 概要

describe の単体テストの fixture `no_warnings` が参照する `request.node.name` の型の違反を解消し、develop で `pyright` を違反 0 件で合格させる。

## 背景

[Issue #45](https://github.com/shuhei1101/project-index/issues/45) の要望。
[#42](https://github.com/shuhei1101/project-index/pull/42) の lint で、develop（[81f0e70](https://github.com/shuhei1101/project-index/commit/81f0e70ecda123ed3ed882b54e33fbbe4ad29d68)）の [tests/unit/project_index/features/describe/test_service.py](https://github.com/shuhei1101/project-index/blob/81f0e70ecda123ed3ed882b54e33fbbe4ad29d68/tests/unit/project_index/features/describe/test_service.py) の 43 行目に `reportUnknownMemberType` が 2 件出ることを見つけた。
develop にこの違反がある間は、どの作業 PR の lint も終了コード 1 で終わる。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの単体テストの計画書 |

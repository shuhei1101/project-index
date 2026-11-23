# 結合テストの準備の _direct_commit_lines を分けて complexipy の上限以下にする

## 概要

結合テストの準備 `tests/integration/server/conftest.py` の `_direct_commit_lines` を分けて cognitive complexity を complexipy の上限以下にし、lint 層の `uv run complexipy src tests` を合格させる。

## 背景

[Issue #272](https://github.com/shuhei1101/project-index/issues/272) の報告。[#271](https://github.com/shuhei1101/project-index/pull/271) の lint 層で、`_direct_commit_lines` の cognitive complexity が 16 になり、`pyproject.toml` の `max-complexity-allowed`（15）を超えて FAILED になった。base の develop でも同じく FAILED になる既存の違反で、規約『設計原則』の「複雑さは lint で検査する」から外れている。

## 計画書

<!-- table: {"kind": "data"} -->

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

<!-- /table -->

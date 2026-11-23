# 配信元の設定の search_exclude に該当する文書を、読み取り API の文書の一覧・語での検索と list_match_words からも除く

## 概要

配信元の設定の `documents[].search_exclude` に該当する文書の扱いを、読み取り API の文書の一覧・語での検索と文書の MCP の `list_match_words` でも決めて統一し、除いた文書を取得する明示の指定を持たせる。

## 背景

[Issue #254](https://github.com/shuhei1101/project-index/issues/254) の要望（依頼元 [PR #251](https://github.com/shuhei1101/project-index/pull/251)・起点 [Issue #250](https://github.com/shuhei1101/project-index/issues/250)）。
#251 で `search_exclude` に該当する文書を `search_docs`・`list_changes`・`trace_related` の既定の結果から除いたが、#250 の要望が 3 つのツールに限るため、読み取り API の文書の一覧（`list_documents`）・語での検索（`_search`）と `list_match_words`（`terms.py`）はスコープ外にした。
[7153469](https://github.com/shuhei1101/project-index/commit/7153469)（develop）でも、この 3 つのエンドポイントは `search_exclude` を参照していない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 3 つのエンドポイントで除く文書の扱いの計画書 |

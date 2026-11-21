# 配信元の設定で、文書のメタデータの値によって既定の検索から除く文書を指定できるようにする

## 概要

配信元の設定の `documents[]` の行に文書のメタデータの値の条件を記載すると、条件に該当する文書が `search_docs`・`list_changes`・`trace_related` の既定の結果から除かれ、明示の引数を付けたときだけ返却されるようにする。

## 背景

[Issue #250](https://github.com/shuhei1101/project-index/issues/250) の要望（依頼元 [shuhei1101/aituber#191](https://github.com/shuhei1101/aituber/pull/191)）。
aituber のアセットは使用しなくなったら状態を `inactive` にして新規に選ばれないようにするが、アセットは project-index の配信元の文書として検索される。
今の配信元の設定で文書を除けるのは、ファイルのパスの glob の `documents[].exclude[]` と、行全体を検索の対象から除外する `documents[].search`（[docs/guide/設定.md](https://github.com/shuhei1101/project-index/blob/90e690a/docs/guide/%E8%A8%AD%E5%AE%9A.md)）だけで、文書のメタデータの値（`status` など）で除く仕組みが無い。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 既定の検索から除く文書の条件の計画書 |

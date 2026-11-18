# records を持たない行で create の配置先が paths に該当しないときを違反にする

## 概要

エージェントが `records` を持たない種類の文書を `write_docs` の `create` で作るとき、決めた配置先が行の `paths` に該当せず文書にならない場合は、書き込まずに配置先を決められない違反として返却する。

## 背景

[Issue #193](https://github.com/shuhei1101/project-index/issues/193) の要望。
`new_document_path` は、`records` を持たない行で `paths` の先頭のファイル名に `*` が無く、glob がフォルダの階層だけにあるとき（例: `docs/*/README.md`）も違反にしない。
ファイル名の `*` の置き換えが何もせず、glob を含むフォルダの階層は取り除かれるため、どの ID でも同じファイル `docs/README.md` が配置先になり、そのファイルは `paths` に該当しないので書き込んでも文書にならない。
[PR #191](https://github.com/shuhei1101/project-index/pull/191)（[Issue #189](https://github.com/shuhei1101/project-index/issues/189)）のレビューで挙がり、修正案の文言だけを扱う #189 のスコープ外として切り出した。
[受付判断](https://github.com/shuhei1101/project-index/issues/193#issuecomment-6971001965)で、違反にするのは配置先が `paths` に該当しないときに限り、配置先が `paths` に該当する `docs/**/index.yaml` の型は今の振る舞いを維持すると決めた。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

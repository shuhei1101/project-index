# write_docs の rename で、配信元の外を指す new_path を断る

## 概要

`write_docs` の 1 ファイル 1 文書の `rename` で、配信元の外を指す `new_path` を何も書き込まずに断る。

## 背景

[Issue #295](https://github.com/shuhei1101/project-index/issues/295) の要望。
[#294](https://github.com/shuhei1101/project-index/pull/294) のレビューで、`paths` が `**` で始まる種類の文書を `new_path: ../outside/x.yaml`・`/tmp/x.yaml` で `rename` すると、配信元の外へファイルを移すことが分かった。
[src/project_index/features/write/service.py](https://github.com/shuhei1101/project-index/blob/cbc155d/src/project_index/features/write/service.py) の `_plan_file_move` は、正規化した `new_path` を `DocumentTable.matches` と既にあるファイルの確認だけで確かめ、`**` で始まるパターンは配信元の外を指すパスにも該当する。
SC-7『エージェントが書き込む』の `minimal_guarantee`（本文のファイルのパスが配信元の外を指す書き込みは、ファイルを 1 つも書き換えない）から外れている。
#294 で `create` の `new_path` に同じ確認（[placement.py](https://github.com/shuhei1101/project-index/blob/cbc155d/src/project_index/features/write/placement.py) の `requested_document_path`）を追加した。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

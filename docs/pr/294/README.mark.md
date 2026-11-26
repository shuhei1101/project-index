# write_docs の create で、配置先のパスを new_path で指定できるようにする

## 概要

エージェントや管理画面が `write_docs` の `create` に作成するファイルのパスを指定して、フォルダの階層に glob を持つ種類の文書（キャラクターごとのフォルダの文書など）を作成できるようにする。

## 背景

[Issue #293](https://github.com/shuhei1101/project-index/issues/293) の要望。
aituber の作業 PR [shuhei1101/aituber#292](https://github.com/shuhei1101/aituber/pull/292) が、管理画面と MCP のツールから `portrait/{キャラクター ID}/{アセット ID}.yaml`・`portrait/{キャラクター ID}/definition.yaml` へ文書を作成して develop へ直コミットする。
今の `create` は配置先を種類の行の `paths` の先頭の glob から決める（[src/project_index/features/write/placement.py](https://github.com/shuhei1101/project-index/blob/b20da1cc8b859a6901d6daee764533c77e8afc7d/src/project_index/features/write/placement.py) の `new_document_path`）。
`portrait/*/*.yaml` のようにフォルダの階層に glob を持つ行は、glob の階層を取り除いた配置先が `paths` に該当しないため「配置先を決められません」で断る。
`**` にしても、キャラクターごとのフォルダには配置できない。
ファイルのパスを指定する `new_path` は、今は `rename` だけが受ける。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

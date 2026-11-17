# write_docs の add_to・remove_from で x-key の値で配列の要素を指し、管理用の YAML に無いファイルの判定で .git のファイルと .gitignore に該当するファイルを数えない

## 概要

エージェントが `write_docs` の `add_to`・`remove_from` で `x-key` の値で配列の要素を指して書き込め、書き込めないパスは違反で知れるようになる。
利用者が worktree から配信した配信元で、`.git` のファイルと Git が無視するファイルを「管理用の YAML に無いファイル」に数えなくなる。

## 背景

[#158](https://github.com/shuhei1101/project-index/issues/158) は、同じタグの 3 件を 1 つの作業 PR で扱う束の親 Issue。

- [#151](https://github.com/shuhei1101/project-index/issues/151): `add_to`・`remove_from` に要素の選び方（`[...]`）を含むパスを指定すると、`get_field` が新規作成したリストへ追加するため、`applied: true` を返却するのにファイルが変わらない。`x-key` の値で要素を指せるのは [#143](https://github.com/shuhei1101/project-index/pull/143) で入れた `text_edits` だけ
- [#154](https://github.com/shuhei1101/project-index/issues/154): `indexable.py` の `SKIP_DIRS` は `.git` をフォルダとしてだけ除くため、worktree の `.git`（1 行のファイル）が数えられる
- [#156](https://github.com/shuhei1101/project-index/issues/156): 判定が `.gitignore` を参照しないため、キャッシュ・生成物が数えられる。[#155](https://github.com/shuhei1101/project-index/pull/155) では直下の `project-index.yaml` の `root` の行の `exclude` に `.gitignore` の行をコピーして回避した

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

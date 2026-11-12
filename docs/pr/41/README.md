# write_docs で worktree を指定したとき、そのワークツリーの配信元の設定で種類を参照する

## 概要

エージェントが、作業ブランチの配信元の設定に追加した種類の文書を、`worktree` を指定した `write_docs` で作成できるようになる。

## 背景

[Issue #35](https://github.com/shuhei1101/project-index/issues/35) の不具合（[shuhei1101/dev-docs#167](https://github.com/shuhei1101/dev-docs/issues/167) から移した Issue）。
[shuhei1101/knowledge#291](https://github.com/shuhei1101/knowledge/pull/291) で、作業ブランチの `dev-docs.yaml` に種類 `terms` を追加した後、`worktree` を指定した `write_docs` の `create` が `UnknownKindError` を返却した。
同じ `worktree` を指定した `describe` は、作業ブランチの設定のとおり `terms` を返却する。

`describe` は、読む場所がワークツリーのとき `load_source_at` でその場所の設定を読み直した配信元に差し替える。
書き込みの側の `resolve_write_target` は登録済みの配信元（develop の設定）をそのまま `Target` に入れるため、`write_docs` はワークツリーの設定に追加した種類を参照できない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

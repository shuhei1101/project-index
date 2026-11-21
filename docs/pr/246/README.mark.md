# delete_docs でスキルの ref の参照先のエージェントフローを削除する操作を断る

## 概要

エージェントが、ほかのスキルの `ref` が指すエージェントフローを `delete_docs` で削除しようとすると、削除の前に断られ、参照しているエージェントフローと `ref` を受け取れるようにする。

## 背景

[Issue #245](https://github.com/shuhei1101/project-index/issues/245) の要望（依頼元 [#243](https://github.com/shuhei1101/project-index/pull/243) のスコープ外の行）。
#243 で `write_docs` は `project-index skill-md --check` の `validators[]` で SKILL.md を組み立てられなくなる書き込みを断るようになったが、`delete_docs` は `validators[]` を実行しない（[docs/interface/IF-7.yaml](https://github.com/shuhei1101/project-index/blob/9d95b0f/docs/interface/IF-7.yaml)）。
このため `ref` の参照先を削除すると削除は成功し、後の `generators[]` の生成の失敗がサーバーのログに残るだけで、SKILL.md は前の中身のまま残る。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 削除の前の検査の計画書 |

# クローンが既に最新で稼働中のプロセスだけが更新前のコードのときも update で起動し直す

## 概要

利用者が管理の MCP の `update` を呼ぶと、クローンが既に最新でも、稼働中のプロセスが更新前のコードなら起動し直して新しいコードを効かせられるようになる。

## 背景

[#286](https://github.com/shuhei1101/project-index/issues/286) の不具合。
[#282](https://github.com/shuhei1101/project-index/pull/282)（起点 Issue [#281](https://github.com/shuhei1101/project-index/issues/281)）の反映作業『索引のサーバーの更新』は `update` を呼び、`restarting: true` のときだけ成功にしていた。
稼働中の `project-index serve` のクローン（develop の worktree）は、マージの後のローカルの最新化で既に squash commit f90d462 まで fast-forward されていたため、`update` は取り込む commit が無いとして `updated: false`・`restarting: false` を返し、稼働中のプロセスは更新前のコードのまま残った。
`update` は `git pull --ff-only` の前後の HEAD だけを比べ、稼働中のプロセスが起動した commit とは比べていない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

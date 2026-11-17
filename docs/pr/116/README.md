# テスト実行方法の層ごとに実行場所を決め、ランナーで回せる層を GitHub Actions の workflow で回す

## 概要

開発者が、テスト実行方法の層のうちランナーで回せる層を GitHub Actions のランナーで回し、ランナーで回せないときは手元で回せるようになる。

## 背景

[Issue #72](https://github.com/shuhei1101/project-index/issues/72) の要望。
全プロジェクトの単体・結合テストが同じ WSL の上で回り、手元のメモリが足りなくなっている。
[テスト実行方法](../../test-procedure/TP-1.yaml) の全ての層が手元で回す前提で記載されていて、層ごとの実行場所が無く、テストを回す workflow も無い。

依存先の [knowledge#350](https://github.com/shuhei1101/knowledge/issues/350)・[knowledge#351](https://github.com/shuhei1101/knowledge/issues/351)・[ai-monitor#3434](https://github.com/shuhei1101/ai-monitor/issues/3434)・[#69](https://github.com/shuhei1101/project-index/issues/69) は全て close 済み。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | テスト実行方法・workflow の計画書 |

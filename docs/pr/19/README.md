# リポジトリの直下の配信元の設定 dev-docs.yaml を project-index.yaml へ改名する

## 概要

このリポジトリの直下の配信元の設定 `dev-docs.yaml` を、既定のファイル名 `project-index.yaml` へ改名する。

## 背景

[Issue #16](https://github.com/shuhei1101/project-index/issues/16) の要望。
[#15](https://github.com/shuhei1101/project-index/pull/15)（起点 [#14](https://github.com/shuhei1101/project-index/issues/14)）で配信元の設定の既定のファイル名を `project-index.yaml` にしたが、このリポジトリの直下は移行の間に読む `dev-docs.yaml` のまま残っている。
#15 の要件のスコープ外の行から切り出した。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [反映作業](./反映作業/index.yaml) | 端末の設定の `sources[].config` の修正 |

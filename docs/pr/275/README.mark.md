# 画面のサーバーの書き込みの API から配信元の設定（project-index.yaml）を直コミットで書き換えられるようにするか決めて対応する

## 概要

dev-docs の画面のサーバーが、書き込みの API（`POST /sources/{source}/commits`）で配信元の設定 `project-index.yaml` を直コミットで書き換えられるようにするかを決め、扱う場合は検査と直コミットの許可を含めて対応する。

## 背景

[#252](https://github.com/shuhei1101/project-index/issues/252)（作業 PR [#256](https://github.com/shuhei1101/project-index/pull/256)）で書き込みの API を追加したが、対象は管理用の YAML・用語集など配信元の文書に限った。
後続の [shuhei1101/dev-docs#310](https://github.com/shuhei1101/dev-docs/issues/310) は、画面から配信元の設定 `project-index.yaml` も修正したいとしている。
起点は [#258](https://github.com/shuhei1101/project-index/issues/258)。
rule-inject の索引は [#270](https://github.com/shuhei1101/project-index/issues/270) で配信元の文書として配信するため対象外。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理と影響する UC 一覧 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

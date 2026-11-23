# prompt-doc がプロンプトの部品の x-each とロールごとのメッセージの区切りを描画する

## 概要

`project-index prompt-doc` が、プロンプトの部品の `x-each`（配列の要素ごとに部品を繰り返す）を要素ごとに描画し、`kind: llm` の例の組を、並び順のまま続く同じロールの部品ごとのメッセージに区切って描画する。

## 背景

[#277](https://github.com/shuhei1101/project-index/issues/277) の要望。
aituber の [shuhei1101/aituber#221](https://github.com/shuhei1101/aituber/pull/221)（起点 [shuhei1101/aituber#152](https://github.com/shuhei1101/aituber/issues/152)）で、プロンプトファイル `content/prompts/node/generate-lines.yaml` が `x-each` と `assistant` のロールの部品を使用し始めた。
aituber の描画（`src/aituber/integrations/llm/prompts/builder.py` の `build_messages`）は、`x-each` の部品を配列の要素ごとに描き、連続する同じロールの部品を 1 通のメッセージにまとめる。
今の `prompt-doc` は `x-each` を参照せずに部品を 1 回だけ描き、部品をロールごとにつないで `system`・`user`・`assistant` の順に並べるため、文書の画面の会話履歴が実際に送信するメッセージと違う構造で出る。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理と影響する UC 一覧 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

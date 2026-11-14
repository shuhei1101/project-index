---
tags: [判定フローチャート, documents, 設定]
---

# documentsの行の判定

文書を既存の documents の行に入れるか、新しい行（新しいスキーマ）を作るかを決める判定フローチャート

documents の行は、`project-index.yaml` の `documents[]` の 1 行です。
各キーは [設定](./設定.md) の `documents[]` にあります。

## 判定フローチャート

<!-- map: {"title": "documents の行の判定"} -->

```mermaid
flowchart TD
  START([文書を 1 件、documents の行に入れたい])
  Q1{Q1 同じ種類※1の文書を扱う既存の行があるか?}
  Q2{Q2 文書の形式※2が、その行の records・body_file に合うか?}
  Q3{Q3 文書の項目が、その行の schema に収まる※3か?}
  Q4{Q4 文書の配置先が、その行の paths に当たり、exclude に当たらないか?}
  Q5{Q5 文書を、その行の validators の検査に通る内容にできるか?}

  A1([その行の paths に、文書の配置先を追加する。配置先のファイル名が exclude に当たるときは、当たらない配置先に変える])
  R1([その行に入れる])
  R2([新しい行を作る（新しいスキーマを作る）])

  START --> Q1
  Q1 -->|NO| R2
  Q1 -->|YES| Q2
  Q2 -->|YES| Q3
  Q2 -->|NO| R2
  Q3 -->|NO| R2
  Q3 -->|YES| Q4
  Q4 -->|YES| Q5
  Q4 -->|NO| A1
  A1 --> Q5
  Q5 -->|YES| R1
  Q5 -->|NO| R2
```

<!-- /map -->

- **※1 種類**: 文書が説明する対象の種類（規約・シナリオ・設計書 など）。`describe(source)` の `kinds[]` の名前（行の `title`・スキーマの `title`）と比べる
- **※2 形式**: YAML の 1 ファイルが 1 文書か、配列の各要素が 1 文書か（`records`）、本文が別のファイルか（`body_file`）。ソースコードなど YAML でない文書は管理用の YAML の `files[]` の 1 行として扱い、`records: files`・`body_file: path` の行が形式に合う行になる
- **※3 収まる**: 文書が `schema` の必須の項目を全て持ち、持たせたい項目が全て `schema` にあること。`describe(source, kind)` でスキーマを見て確かめる。列名が共通のキー（`name`・`tags` など）と違うだけなら行の `metadata` の列名の対応が読み替えるので、収まらない理由にしない。`schema` の無い行は収まるものとする

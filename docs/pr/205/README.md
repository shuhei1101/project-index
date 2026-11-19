# 書き込みの後に管理用の YAML などの修正を促すフックの通知と、会話の指摘を登録するスキルを追加する

## 概要

エージェントが配信元のフォルダの下のファイルを書き換え・作成した後に、管理用の YAML・エイリアス・ルールの索引の修正をフックの通知で受け取れるようにする。
利用者が、会話で AI に伝えた指摘を、スキルでルール・エイリアス・文書として登録できるようにする。

## 背景

[Issue #204](https://github.com/shuhei1101/project-index/issues/204) は、[#199](https://github.com/shuhei1101/project-index/issues/199) と [#202](https://github.com/shuhei1101/project-index/issues/202) を 1 本の作業 PR で行う束の親 Issue。

- #199: プラグインのフックは SessionStart と、文書の MCP のツールの PreToolUse だけ（[plugins/project-index/hooks/hooks.json](https://github.com/shuhei1101/project-index/blob/1ad0764/plugins/project-index/hooks/hooks.json)）。Write・Edit・ほかの MCP のツールでの書き込みの後には何も走らず、管理用の YAML の行の修正は MCP の instructions の 1 行と、スキル `setup` の 2 回目以降の突き合わせに頼っている。作業の途中では忘れられ、行の無いファイルと、中身と合わないメタデータが残る
- #202: 利用者が会話で AI に指摘した内容（守ってほしいこと・単語の意味・経緯や判断の理由）は、会話が終わると残らない。残すには rule-inject の索引・用語集・文書を手で記載するか、その都度 AI に依頼する必要がある

両方の前提だった [#200](https://github.com/shuhei1101/project-index/issues/200)（[#201](https://github.com/shuhei1101/project-index/pull/201)）で、メタデータを付ける基準が [docs/guide/メタデータを付ける基準.md](https://github.com/shuhei1101/project-index/blob/1ad0764/docs/guide/%E3%83%A1%E3%82%BF%E3%83%87%E3%83%BC%E3%82%BF%E3%82%92%E4%BB%98%E3%81%91%E3%82%8B%E5%9F%BA%E6%BA%96.md) に移り、配信元を登録していない端末でも文書の MCP から取得できるようになった。
通知とスキルは、どちらもこの基準を指す。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [プラグイン](./プラグイン.md) | プラグインの計画書 |

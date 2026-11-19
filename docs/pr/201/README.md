# 配信元の登録・見直しの手順とメタデータを付ける基準をガイドへ移し、配信元が無い端末でも MCP から取得できるようにする

## 概要

エージェントが、スキル `setup` を起動していないときにも、配信元の登録・見直しの手順と、メタデータ・エイリアスを付ける基準を project-index の文書の MCP から取得できるようにする。

## 背景

[Issue #200](https://github.com/shuhei1101/project-index/issues/200) の要望。配信元の登録・見直しの手順（範囲の決め方・仮のメタデータの付け方・タグ・関連の候補・alias-inject との紐づけ）が、スキル `setup` の [SKILL.md](https://github.com/shuhei1101/project-index/blob/develop/plugins/project-index/skills/setup/SKILL.md) の本文に組み込まれている。

- 手順はスキルを起動したときにしか読まれず、作業の途中でファイルを足した・書き換えたときに同じ基準を参照できない
- 手順を変えるたびに、プラグインの更新と配布が要る

利用者の端末の設定は `sources: []` で始まり（[templates/settings.yaml](https://github.com/shuhei1101/project-index/blob/develop/templates/settings.yaml)）、配信元 `project-index` は登録されない。ガイドのページを追加するだけでは `search_docs` で読めないため、配信元が登録されていない端末でも手順を返す経路を索引のサーバーに追加する（[受付判断のレビュー](https://github.com/shuhei1101/project-index/issues/200#issuecomment-7003373757)）。

[#199](https://github.com/shuhei1101/project-index/issues/199)（書き込みの後のフックの通知）は、この手順の該当する箇所を通知から指す後続。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |
| [プラグイン](./プラグイン.md) | プラグインの計画書 |

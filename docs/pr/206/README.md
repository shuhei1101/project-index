# メタデータを付ける基準を判定フローチャートに整理し、エイリアスを付ける基準を加える

## 概要

エージェントが、メタデータとエイリアスを付けるときに、`docs/guide/メタデータを付ける基準.md` の判定フローチャートをたどって付ける内容を決められるようにする。

## 背景

[Issue #203](https://github.com/shuhei1101/project-index/issues/203) の要望。[PR #201](https://github.com/shuhei1101/project-index/pull/201) でスキル `setup` の基準を `docs/guide/メタデータを付ける基準.md` へ移したが、中身は SKILL.md の箇条書きと表のままで、`docs/guide/` の既存の判定フローチャート（[documentsの行の判定](https://github.com/shuhei1101/project-index/blob/1ad0764/docs/guide/documents%E3%81%AE%E8%A1%8C%E3%81%AE%E5%88%A4%E5%AE%9A.md)・[新しく作るか修正するかの判定](https://github.com/shuhei1101/project-index/blob/1ad0764/docs/guide/%E6%96%B0%E3%81%97%E3%81%8F%E4%BD%9C%E3%82%8B%E3%81%8B%E4%BF%AE%E6%AD%A3%E3%81%99%E3%82%8B%E3%81%8B%E3%81%AE%E5%88%A4%E5%AE%9A.md)）の構成になっていない。

エイリアス（`aliases`）をいつ・どの文書に付けるかの基準は無く、エイリアスに関わる記述は [配信元を登録する](https://github.com/shuhei1101/project-index/blob/1ad0764/docs/guide/%E9%85%8D%E4%BF%A1%E5%85%83%E3%82%92%E7%99%BB%E9%8C%B2%E3%81%99%E3%82%8B.md) の手順 6 の alias-inject の設定との紐づけだけにある（[PR #201 のマージ提案への reviewer の指摘](https://github.com/shuhei1101/project-index/pull/201#discussion_r4626940680)）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |

## テスト結果

単体・結合テストは実行しない。変更は `docs/guide/` のページの本文と目次・管理用の YAML の行だけで、コードを変えない。基準のページを参照する結合テスト（`tests/integration/server/test_search_docs.py`・`test_serve.py`）は、ページのパスだけを使用し、本文は `conftest.py` の固定の文字列を使用するため影響しない。

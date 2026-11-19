# write_docs・delete_docs に、書き込みの後に既定のブランチへコミットしてプッシュする指定（直コミット方式）を追加する

## 概要

手元のセッションが、`write_docs`・`delete_docs` にコミットの指定を付けて呼ぶと、書き込みの後に既定のブランチへコミットしてプッシュするところまでを 1 回の呼び出しで終えられるようにする。
直コミットを許可する種類は、配信元ごとの設定で決める。

## 背景

[Issue #209](https://github.com/shuhei1101/project-index/issues/209) の要望。
knowledge などに、レビューが要らないデータ（ネットミーム・用語・対応表の行・ノウハウ）を追加するたびに、Issue を起票して作業 PR で登録しており、手順が重い。手元だけに持つと消える恐れがある。

今の `write_docs`・`delete_docs`（[docs/interface/IF-6.yaml](https://github.com/shuhei1101/project-index/blob/d1402c9/docs/interface/IF-6.yaml)・[docs/interface/IF-7.yaml](https://github.com/shuhei1101/project-index/blob/d1402c9/docs/interface/IF-7.yaml)）は作業ツリーのファイルを書き換えるだけで、コミットとプッシュは呼んだ側が行う。
手元のセッションは配信元のフォルダの外部の作業場所から呼ぶため、コミットとプッシュを自分で行えない。

ツールを持つ場所は、利用者が project-index の `write_docs`・`delete_docs` へ追加する案に決めた。
規約の本文など、エージェントの動きを変える文書は、最初は対象にしない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [要件.yaml](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

# setup の検索の範囲を全てのファイルにし、関連の候補・alias-inject との突き合わせ・メタデータの偏りの洗い出しを追加する

## 概要

setup の利用者が、プロジェクトの配下の全てのファイルを検索の対象にでき、種類とキーを知らなくても関連の候補を受け取り、alias-inject の設定とのずれと、仮のメタデータの偏りに気付けるようになる。

## 背景

束の親 [Issue #112](https://github.com/shuhei1101/project-index/issues/112) の要望で、[#102](https://github.com/shuhei1101/project-index/issues/102)・[#107](https://github.com/shuhei1101/project-index/issues/107)・[#108](https://github.com/shuhei1101/project-index/issues/108)・[#110](https://github.com/shuhei1101/project-index/issues/110) を扱う。
setup の手順 3 は検索の範囲の既定を `**/*.md` にし、Git が無視するファイルを既定で除外するため、コードやスクリプトは検索の対象に入らない。
関連の候補は `tests` と、ユーザーが回答した種類とキーによる `implements` だけで、既定のままでは `implements` が付かず、既に管理用の YAML にある行には候補が付かない。
setup は alias-inject の端末の設定に触れず、2026-11-17 に設定のファイルの改名で照合から外れた配信元があった。
[#106](https://github.com/shuhei1101/project-index/pull/106) で仮のメタデータを段階的に付けるようにしたが、付けた後の `description` の重なりとタグの偏りは見直していない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [プラグイン](./プラグイン.md) | setup スキルの計画書 |
| [索引のサーバー](./索引のサーバー.md) | CLI のサブコマンドの計画書 |
| [しきい値の測定](./しきい値の測定/README.md) | `project-index skew` の類似度のしきい値を導いた記録 |

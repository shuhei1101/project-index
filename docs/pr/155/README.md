# project-index 自身の配信元の直下に管理用の YAML を配置し、直下と docs/ 直下のファイルを記載する

## 概要

project-index 自身の配信元の直下に管理用の YAML を置き、直下のファイルと `docs/` 直下のファイルを文書として検索できるようにする。

## 背景

[Issue #149](https://github.com/shuhei1101/project-index/issues/149) の要望。
[#141](https://github.com/shuhei1101/project-index/pull/141) で「管理用の YAML に無いファイル」の判定が、より深いフォルダの管理用の YAML の範囲と `exclude` のパスの glob に当たるファイルを数えなくなった。
これで配信元の直下に管理用の YAML を置けるようになったが、project-index 自身の配信元の設定は変えておらず、直下と `docs/` 直下のファイルはどの管理用の YAML にも載っていない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |

# serve がログのハンドラを閉じた後に、裏のスレッドがログのファイルを開き直して残さないようにする

## 概要

`project-index serve` がログのハンドラを閉じた後に、裏のスレッドのログでログのファイルが開き直されて閉じられないまま残らないようにし、単体テスト `test_run_serve_when_restart` が不定に error にならないようにする。

## 背景

[Issue #266](https://github.com/shuhei1101/project-index/issues/266) の報告。[#265](https://github.com/shuhei1101/project-index/pull/265) の CI（run 45090913499）で `test_run_serve_when_restart` が `ResourceWarning: unclosed file ... project-index.log` から `PytestUnraisableExceptionWarning` で error になり、直後の run では pass した。
`run_serve` は `start_loading` で裏のスレッドを動かしたまま `_close_logging` でハンドラを閉じる。`RotatingFileHandler` は閉じた後に `emit` されるとファイルを開き直すため、外す直前にハンドラを掴んだ裏のスレッドが閉じた後に書くと、開き直したファイルが残る競合が見立てとして挙がっている。

## 計画書

<!-- table: {"kind": "data"} -->

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理と変更箇所の由来 |
| [索引のサーバー](./索引のサーバー.mark.md) | 索引のサーバーの計画書 |

<!-- /table -->

# 単体テストの test_check_port 系がランナーでときどき PortInUseError で fail する不具合を修正する

## 概要

単体テストの層をランナーで回したときに、`test_serve.py` のポートの確認のテストが同じ commit で pass と fail を繰り返さないようにする。

## 背景

[Issue #126](https://github.com/shuhei1101/project-index/issues/126) の不具合。
単体テストの層を `gh workflow run test.yml -f layer=unit` で回すと、[tests/unit/project_index/test_serve.py](https://github.com/shuhei1101/project-index/blob/8f5fa84/tests/unit/project_index/test_serve.py) の `test_check_port`・`test_check_port_when_time_wait` が `PortInUseError: 127.0.0.1:{ポート} は使用中です` でときどき fail し、同じ commit で回し直すと pass する。
作業 PR ごとに回し直しが要る。
報告元は作業 PR [#122](https://github.com/shuhei1101/project-index/pull/122)（起点 Issue [#75](https://github.com/shuhei1101/project-index/issues/75)）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.md) | 索引のサーバーの計画書 |

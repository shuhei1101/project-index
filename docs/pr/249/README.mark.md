# 削除した type: skill のエージェントフローの SKILL.md を後片付けする

## 概要

`type: skill` のエージェントフローを削除すると、その `skill.path` の SKILL.md も消え、生成元の無い SKILL.md が配布物に残らないようにする。

## 背景

[Issue #248](https://github.com/shuhei1101/project-index/issues/248) の要望（依頼元 [#246](https://github.com/shuhei1101/project-index/pull/246) のスコープ外の行）。
`project-index skill-md` の生成のモード（[docs/interface/IF-37.yaml](https://github.com/shuhei1101/project-index/blob/89a8970/docs/interface/IF-37.yaml)）は、組み立てた中身と違う SKILL.md を書き換えるだけで、生成元が無くなった SKILL.md を削除しない。
このため `delete_docs` でスキルのエージェントフローを削除しても、その後に流れる `generators[]` では SKILL.md が消えず、削除したスキルが配られ続ける。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [索引のサーバー](./索引のサーバー.mark.md) | 生成元の無い SKILL.md の削除の計画書 |

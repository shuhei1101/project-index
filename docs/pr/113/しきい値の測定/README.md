# しきい値の測定

`project-index skew` が「ほぼ同じ `description`」とみなすしきい値を、既存の配信元の管理用の YAML で測った記録。

## 測り方

`description` を NFKC・casefold にし、空白と記号を除いた文字列の、文字 bigram の Dice 係数で比べる。
[measure_similarity.py](./measure_similarity.py) で、配信元ごとに全ての組の係数を求めた（出力は [measure_similarity.log](./measure_similarity.log)）。

| 配信元 | 行 | 組 | 0.95 以上 | 0.9 以上 | 0.85 以上 | 0.8 以上 |
| --- | --- | --- | --- | --- | --- | --- |
| project-index（develop） | 251 | 31375 | 0 | 29 | 82 | 237 |
| knowledge（develop） | 17 | 136 | 0 | 0 | 1 | 1 |

0.9 以上の組は、`検索の service.py の単体テストを受け持ち…` と `検査の service.py の単体テストを受け持ち…` のように、名詞 1 単語だけが違う定型の `description` だった。
助詞 1 字だけが違う 36 字の組（SC-5 の `正常シナリオ（仮のメタデータの偏りを見直す）` の型）は 0.9375 になる。

## 決めた値

しきい値は 0.9 以上にする。
助詞 1 字の違いを検出し、名詞 1 単語だけが違う定型の組（`description` から対象を見分けにくい組）までを見直しの候補に出す。
0.85 にすると、project-index で候補が 82 組になり、見直しの表を確認しきれない量になる。

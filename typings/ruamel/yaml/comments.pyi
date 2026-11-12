# ruamel.yaml の CommentedMap は型引数を持たず、値が Unknown になるため、使用する分だけ型を宣言する
from typing import Any

class Comment:
    items: dict[Any, Any]

class CommentedBase:
    @property
    def ca(self) -> Comment: ...

class CommentedMap(dict[Any, Any], CommentedBase):
    def insert(
        self, pos: int, key: object, value: object, comment: object | None = None
    ) -> None: ...

class CommentedSeq(list[Any], CommentedBase): ...

# YAML の load・dump は引数の型が Unknown になるため、使用する分だけ型を宣言する
from collections.abc import Callable
from pathlib import Path
from typing import IO

class Representer:
    def add_representer(
        self, data_type: type, representer: Callable[[Representer, str], object]
    ) -> None: ...
    def represent_scalar(self, tag: str, value: str, style: str | None = None) -> object: ...

class YAML:
    width: int | None
    preserve_quotes: bool | None
    default_flow_style: bool | None
    allow_unicode: bool
    def __init__(self, *, typ: str | list[str] | None = None, pure: bool = False) -> None: ...
    @property
    def representer(self) -> Representer: ...
    def indent(
        self, mapping: int | None = None, sequence: int | None = None, offset: int | None = None
    ) -> None: ...
    def load(self, stream: Path | str | IO[str]) -> object: ...
    def dump(self, data: object, stream: Path | IO[str]) -> None: ...

"""読み取り API と端末の設定の API の DTO の基底。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """読み取り API と端末の設定の API の入出力の DTO の基底。JSON のキーを camelCase にする。"""

    model_config = ConfigDict(
        alias_generator=to_camel, validate_by_name=True, serialize_by_alias=True
    )

"""内容のハッシュ（文書のバージョン）。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

VERSION_LENGTH = 6


def content_hash(data: str | bytes) -> str:
    """内容の SHA-256 の先頭 VERSION_LENGTH 桁を返す。"""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()[:VERSION_LENGTH]


def value_hash(value: Any) -> str:
    """項目の値を正規化した JSON にしてハッシュを取る。"""
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return content_hash(text)

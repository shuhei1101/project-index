"""`ids.format` からの ID の作成。"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

ID_FALLBACK_SLUG = "doc"
NON_SLUG = re.compile(r"[^a-z0-9]+")


def generate_id(fmt: str, *, kind: str, data: Mapping[str, Any], existing: Collection[str]) -> str:
    """`ids.format` の `{kind}`・`{slug}` を埋めて、配信元の中で重ならない ID を作る。"""
    name = unicodedata.normalize("NFKC", str(data.get("name", ""))).lower()
    slug = NON_SLUG.sub("-", name).strip("-") or ID_FALLBACK_SLUG
    base = fmt.replace("{kind}", kind).replace("{slug}", slug)
    candidate, number = base, 1
    while candidate in existing:
        number += 1
        candidate = f"{base}-{number}"
    return candidate

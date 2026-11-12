"""`converters[]` の実行と結果の控え。"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from project_index.features.access.types import Target, script_at
from project_index.features.convert.types import Converted, ConvertFailure
from project_index.integrations.scripts import (
    ScriptError,
    ScriptFailedError,
    ScriptTimeoutError,
    run_script,
)
from project_index.shared.errors import ConverterNotDefinedError
from project_index.shared.files import replace_file
from project_index.shared.hashing import value_hash
from project_index.shared.version import RUNNING_VERSION

if TYPE_CHECKING:
    from pathlib import Path

    from project_index.features.documents.store import DocumentStore
    from project_index.features.documents.types import Document

logger = logging.getLogger(__name__)

CONVERT_CACHE_KEEP = 2000

__all__ = ["CONVERT_CACHE_KEEP", "ConvertService", "run_script"]


class ConvertService:
    """文書の種類が指す `converters[]` のスクリプトで、文書を Markdown にする。"""

    def __init__(self, cache_dir: Path, store: DocumentStore, timeout_sec: float) -> None:
        self.cache_dir = cache_dir
        self.store = store
        self.timeout_sec = timeout_sec

    def _cache_path(
        self, target: Target, document: Document, converter: str, run: list[str]
    ) -> Path:
        """`converters[]` の結果の控えのファイルを返す。"""
        # project-index が持つ変換（`project-index prompt-doc`）の出力は project-index の更新で変わるため、バージョンも含める
        parts = (
            target.source.id,
            document.kind,
            converter,
            document.version,
            value_hash(run),
            RUNNING_VERSION,
        )
        name = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:32]
        return self.cache_dir / f"{name}.md"

    def _prune(self) -> None:
        """控えが `CONVERT_CACHE_KEEP` を超えたら、更新日時が古いものから消す。"""
        files = [item for item in self.cache_dir.glob("*.md") if item.is_file()]
        excess = len(files) - CONVERT_CACHE_KEEP
        if excess <= 0:
            return
        for item in sorted(files, key=lambda file: file.stat().st_mtime)[:excess]:
            item.unlink(missing_ok=True)

    def _run_converter(
        self, target: Target, document: Document, converter: str
    ) -> str | ConvertFailure:
        """`converters[]` のスクリプトで Markdown にする（`cache` の行は控えがあればそれを使う）。"""
        entry = target.source.script("converters", converter)
        cache = self._cache_path(target, document, converter, entry.run) if entry.cache else None
        if cache is not None and cache.is_file():
            return cache.read_text(encoding="utf-8")
        script = " ".join(entry.run)
        try:
            result = run_script(
                entry.run,
                cwd=target.config_base,
                stdin=document.body,
                timeout_sec=self.timeout_sec,
                at=script_at(target),
            )
        except ScriptTimeoutError:
            return ConvertFailure(
                reason="timeout",
                kind=document.kind,
                script=script,
                detail=f"{self.timeout_sec:g} 秒",
            )
        except ScriptFailedError as error:
            return ConvertFailure(
                reason="exit", kind=document.kind, script=script, detail=error.reason
            )
        except ScriptError as error:
            return ConvertFailure(
                reason="not_runnable", kind=document.kind, script=script, detail=error.reason
            )
        # `cache: false` の行の変換は控えを書かない
        if cache is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            replace_file(cache, result.stdout)
            self._prune()
        return result.stdout

    def convert(self, target: Target, document: Document) -> Converted:
        """`converters[]` を指す種類の 1 件の文書を Markdown にする。"""
        table = target.source.table(document.kind)
        # 種類が converters[] を指さなければ、変換する対象が無い
        if table.converter is None:
            raise ConverterNotDefinedError(
                message=f"{document.kind}: converters[] を指していない種類です",
                kind=document.kind,
            )
        produced = self._run_converter(target, document, table.converter)
        if isinstance(produced, ConvertFailure):
            return Converted(markdown="", failure=produced)
        return Converted(markdown=produced)

    def clear(self) -> None:
        """`cache_dir` の控えを全て消す。"""
        if not self.cache_dir.is_dir():
            return
        for item in self.cache_dir.iterdir():
            if item.is_file():
                item.unlink(missing_ok=True)

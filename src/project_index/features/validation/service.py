"""文書の検査をまとめて通す。"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Literal

from project_index.features.access.types import Target, script_at
from project_index.features.validation.markdown import (
    MarkdownCheck,
    changed_markdown,
    check_markdown_values,
)
from project_index.features.validation.rules import (
    check_id_format,
    check_related,
    check_schema,
)
from project_index.features.validation.scripts import parse_validator_output
from project_index.integrations.scripts import ScriptError, run_script
from project_index.shared.errors import Violation

if TYPE_CHECKING:
    from collections.abc import Mapping

    from project_index.features.documents.store import DocumentStore
    from project_index.features.documents.types import Document
    from project_index.features.sources.schema_ref import SchemaRef

VALIDATOR_ON_READ_CACHE = 4096

__all__ = ["VALIDATOR_ON_READ_CACHE", "DocumentChecker", "run_script"]


def _schema_file(schema_path: str | SchemaRef) -> str:
    """違反に書くスキーマのファイル（ほかの配信元の参照は `{配信元}:{パス}@{リビジョン}`）。"""
    if isinstance(schema_path, str):
        return schema_path
    return f"{schema_path.source}:{schema_path.path}@{schema_path.ref}"


class DocumentChecker:
    """1 件の文書に全ての検査を通し、違反をまとめて返す。"""

    def __init__(self, store: DocumentStore, timeout_sec: float) -> None:
        self.store = store
        self.timeout_sec = timeout_sec
        self._read_cache: OrderedDict[tuple[str, str, str, str], list[Violation]] = OrderedDict()
        self._lock = threading.Lock()

    def _run_validator(
        self, target: Target, document: Document, validator_id: str
    ) -> tuple[list[Violation], bool]:
        """検査のスクリプト 1 つを動かし、違反と、動かせたかを返す。"""
        entry = target.source.script("validators", validator_id)
        try:
            result = run_script(
                entry.run,
                cwd=target.config_base,
                stdin=document.body,
                timeout_sec=self.timeout_sec,
                at=script_at(target),
            )
        except ScriptError as error:
            message = " ".join(error.reason.split())
            rule = f"{validator_id}: 検査を実行できませんでした（{message}）"
            return [Violation(path="$", rule=rule)], False
        return parse_validator_output(result.stdout, validator_id=validator_id), True

    def check(
        self,
        target: Target,
        document: Document,
        *,
        on: Literal["read", "write"],
        new: bool = False,
    ) -> list[Violation]:
        """スキーマ・ID の形・関連の種類・`validators[]` を順に通す。"""
        source = target.source
        table = source.table(document.kind)
        violations: list[Violation] = []
        schema = self.store.row_schema(target, document.kind)
        violations.extend(
            check_schema(document.data, schema, schema_file=_schema_file(table.schema_path))
        )
        if new:
            violations.extend(
                check_id_format(document.id, source.config.ids_format, kind=document.kind)
            )
        violations.extend(check_related(document.metadata, source.config.related_types))
        for validator_id in table.validators:
            if on in source.script("validators", validator_id).on:
                violations.extend(self._validate(target, document, validator_id, on=on))
        return violations

    def _validate(
        self, target: Target, document: Document, validator_id: str, *, on: Literal["read", "write"]
    ) -> list[Violation]:
        """`validators[]` の 1 行を通す（読み取りの結果は文書のバージョンごとに控える）。"""
        key = (target.source.id, document.kind, validator_id, document.version)
        if on == "read":
            with self._lock:
                cached = self._read_cache.get(key)
                if cached is not None:
                    self._read_cache.move_to_end(key)
            if cached is not None:
                return cached
        found, ran = self._run_validator(target, document, validator_id)
        # 動かせなかった結果は控えない
        if on == "read" and ran:
            with self._lock:
                self._read_cache[key] = found
                while len(self._read_cache) > VALIDATOR_ON_READ_CACHE:
                    self._read_cache.popitem(last=False)
        return found

    def check_markdown(
        self,
        target: Target,
        document: Document,
        *,
        previous: Mapping[str, Any] | None,
        stopped: str | None = None,
    ) -> MarkdownCheck:
        """書き込む文書の変えた Markdown の値を mdmark の点検に通す。"""
        schema = self.store.row_schema(target, document.kind)
        values = changed_markdown(document.data, previous, schema)
        # Markdown の値を変えていなければ mdmark を呼ばない
        if not values:
            return MarkdownCheck(violations=[], unchecked=[], stopped=stopped)
        return check_markdown_values(
            values, cwd=target.base, timeout_sec=self.timeout_sec, stopped=stopped
        )

    def clear(self) -> None:
        """読み取りの結果の控えを捨てる。"""
        with self._lock:
            self._read_cache.clear()

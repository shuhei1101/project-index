"""項目の操作を当てる。"""
# pyright: reportUnknownArgumentType=warning, reportUnknownMemberType=warning, reportUnknownVariableType=warning

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping, MutableMapping
from typing import TYPE_CHECKING, Any, cast

from project_index.features.documents.fields import delete_field, get_field, set_field
from project_index.shared.errors import InvalidArgumentError, Violation

if TYPE_CHECKING:
    from project_index.features.sources.types import DocumentTable
    from project_index.features.write.types import Operation


def _merge(target: MutableMapping[str, Any], value: Mapping[str, Any]) -> None:
    """オブジェクトは今の値へ再帰でマージし、配列とスカラーは置き換える。"""
    for key, item in value.items():
        if isinstance(item, Mapping) and isinstance(target.get(key), MutableMapping):
            _merge(target[key], item)
        else:
            target[key] = copy.deepcopy(item)


def _set(content: MutableMapping[str, Any], path: str, value: Any) -> None:  # noqa: ANN401
    """項目のパスへ値を入れる（オブジェクトなら今の値へマージする）。"""
    existing = get_field(content, path)
    if isinstance(value, Mapping) and isinstance(existing, MutableMapping):
        _merge(existing, value)
    else:
        set_field(content, path, copy.deepcopy(value))


def _violation(path: str, rule: str, fix: str = "") -> Violation:
    """操作を当てられない違反 1 件を作る。"""
    return Violation(path=path, rule=rule, fix=fix)


def apply_operation(current: Mapping[str, Any] | None, operation: Operation) -> dict[str, Any]:  # noqa: C901
    """文書の内容に 1 件の操作を当てた新しい内容を返す。"""
    if operation.op in ("create", "replace"):
        return copy.deepcopy(operation.data or {})
    content = cast("dict[str, Any]", copy.deepcopy(current if current is not None else {}))
    violations: list[Violation] = []
    for path, value in operation.set.items():
        try:
            _set(content, path, value)
        except InvalidArgumentError as error:
            violations.extend(
                _violation(f"set.{path}", violation.rule) for violation in error.violations
            )
    for path in operation.unset:
        delete_field(content, path)
    for path, values in operation.add_to.items():
        existing = get_field(content, path)
        if existing is None:
            set_field(content, path, [])
            existing = get_field(content, path)
        if not isinstance(existing, list):
            violations.append(_violation(f"add_to.{path}", "配列ではない項目へは追加できません"))
            continue
        existing.extend(copy.deepcopy(item) for item in values)
    for path, values in operation.remove_from.items():
        existing = get_field(content, path)
        if existing is None:
            continue
        if not isinstance(existing, list):
            violations.append(
                _violation(f"remove_from.{path}", "配列ではない項目からは削除できません")
            )
            continue
        existing[:] = [item for item in existing if item not in values]
    for index, edit in enumerate(operation.text_edits):
        text = get_field(content, edit.field)
        prefix = f"text_edits[{index}]"
        if not isinstance(text, str):
            violations.append(
                _violation(f"{prefix}.field", "文字列ではない項目は置き換えられません")
            )
            continue
        count = text.count(edit.old) if edit.old else 0
        if count == 0 or (count > 1 and not edit.replace_all):
            violations.append(
                _violation(
                    f"{prefix}.old",
                    f"old の一致が {count} か所です",
                    f"一致が 1 か所になるよう前後の文字を含めるか、replace_all を true にしてください"
                    f"（一致 {count} 件）",
                )
            )
            continue
        set_field(content, edit.field, text.replace(edit.old, edit.new))
    if violations:
        raise InvalidArgumentError(message="操作を適用できません", violations=violations)
    return content


HEAD_PATTERN = re.compile(r"^([^.\[\]]+)(.*)$")


def _to_column(path: str, metadata: Mapping[str, str]) -> str:
    """項目のパスの先頭のキーが共通のキーなら、列名のパスに置き換える。"""
    matched = HEAD_PATTERN.match(path)
    if matched is None or matched.group(1) not in metadata:
        return path
    return metadata[matched.group(1)] + matched.group(2)


def _check_overlap(
    paths: Iterable[str], metadata: Mapping[str, str], *, item: str, index: int
) -> None:
    """共通のキーと、その列名を同じ項目に両方渡していないかを確かめる。"""
    given = list(paths)
    violations = [
        Violation(
            path=f"operations[{index}].{item}.{path}",
            rule=f"{path} と {_to_column(path, metadata)} は同じ列を指します",
            fix="どちらか 1 つだけを指定してください",
        )
        for path in given
        if (column := _to_column(path, metadata)) != path and column in given
    ]
    if violations:
        raise InvalidArgumentError(
            message=f"引数が正しくありません: {len(violations)} 件", violations=violations
        )


def to_columns(operation: Operation, table: DocumentTable, *, index: int) -> Operation:
    """操作のキーのうち、種類の行の `metadata` に書いた共通のキーを列名へ読み替えた操作を返す。"""
    # 配列の要素を指す列名は、オブジェクトの配列への書き戻しで読み替え済み
    metadata = {key: column for key, column in table.metadata.items() if "[" not in column}
    if not metadata:
        return operation
    for item in ("set", "add_to", "remove_from"):
        _check_overlap(getattr(operation, item), metadata, item=item, index=index)
    _check_overlap(operation.unset, metadata, item="unset", index=index)
    update: dict[str, Any] = {
        "set": {_to_column(path, metadata): value for path, value in operation.set.items()},
        "add_to": {_to_column(path, metadata): value for path, value in operation.add_to.items()},
        "remove_from": {
            _to_column(path, metadata): value for path, value in operation.remove_from.items()
        },
        "unset": [_to_column(path, metadata) for path in operation.unset],
        "text_edits": [
            edit.model_copy(update={"field": _to_column(edit.field, metadata)})
            for edit in operation.text_edits
        ],
    }
    if operation.data is not None:
        _check_overlap(operation.data, metadata, item="data", index=index)
        data: dict[str, Any] = {}
        for key, value in operation.data.items():
            if key in metadata:
                set_field(data, metadata[key], copy.deepcopy(value))
            else:
                data[key] = copy.deepcopy(value)
        update["data"] = data
    return operation.model_copy(update=update)


ALL_KEY_PATTERN = re.compile(r"^(?P<array>[^\[\]]+)\[\]\.(?P<item>[^.\[\]]+)$")
SELECTED_KEY_PATTERN = re.compile(
    r"^(?P<array>[^\[\]]+)\[(?P<flag>[^.\[\]]+)\]\.(?P<item>[^.\[\]]+)$"
)


def _array_keys(
    metadata: Mapping[str, str],
) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str, str]]]:
    """全ての要素のキー（キー → 配列・項目）と選んだ要素のキー（キー → 配列・真偽値のキー・項目）を集める。"""
    all_keys: dict[str, tuple[str, str]] = {}
    selected_keys: dict[str, tuple[str, str, str]] = {}
    for key, column in metadata.items():
        if matched := ALL_KEY_PATTERN.match(column):
            all_keys[key] = (matched["array"], matched["item"])
        elif matched := SELECTED_KEY_PATTERN.match(column):
            selected_keys[key] = (matched["array"], matched["flag"], matched["item"])
    return all_keys, selected_keys


def _original(operation: Operation, current: Mapping[str, Any] | None, array: str) -> list[Any]:
    """書き戻す前の配列の複製（`update` は今の内容、`create`・`replace` は `data` の列名の値）。"""
    source = current if operation.op == "update" else operation.data
    value = get_field(source, array) if source is not None else None
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        return []
    return copy.deepcopy(value)


def _rebuild(elements: list[Any], item: str, names: Iterable[Any]) -> list[Any]:
    """渡した名前の並びで配列を作り直す（元からあった名前の要素は他のキーを保つ）。"""
    by_name = {element.get(item): element for element in elements}
    return [by_name.get(name, {item: name}) for name in names]


def _apply_all_key(
    elements: list[Any], item: str, key: str, operation: Operation, data: Mapping[str, Any]
) -> tuple[list[Any], bool]:
    """全ての要素のキーへの操作を当て、配列と列を削除したかを返す。"""
    if key in data:
        elements = _rebuild(elements, item, data[key])
    if key in operation.set:
        elements = _rebuild(elements, item, operation.set[key])
    if key in operation.add_to:
        present = {element.get(item) for element in elements}
        for name in operation.add_to[key]:
            if name not in present:
                elements.append({item: name})
                present.add(name)
    if key in operation.remove_from:
        removed = operation.remove_from[key]
        elements = [element for element in elements if element.get(item) not in removed]
    return elements, key in operation.unset


def _apply_selected_key(  # noqa: C901
    elements: list[Any],
    names_of: tuple[str, str],
    key: str,
    operation: Operation,
    data: Mapping[str, Any],
    *,
    label: str,
    index: int,
) -> list[Violation]:
    """選んだ要素のキーへの操作を配列へ当て、配列に無い名前の違反を返す。"""
    flag, item = names_of
    by_name = {element.get(item): element for element in elements}
    violations: list[Violation] = []

    def known(names: Iterable[Any], where: str) -> list[Any]:
        found = []
        for name in names:
            if name in by_name:
                found.append(name)
            else:
                violations.append(
                    Violation(
                        path=f"operations[{index}].{where}.{key}",
                        rule=f"{name} は {label} にありません",
                    )
                )
        return found

    if key in data:
        chosen = set(known(data[key], "data"))
        for element in elements:
            if element.get(item) in chosen:
                element[flag] = True
            else:
                element.pop(flag, None)
    if key in operation.set:
        chosen = set(known(operation.set[key], "set"))
        for element in elements:
            if element.get(item) in chosen:
                element[flag] = True
            else:
                element.pop(flag, None)
    if key in operation.add_to:
        for name in known(operation.add_to[key], "add_to"):
            by_name[name][flag] = True
    if key in operation.remove_from:
        for name in operation.remove_from[key]:
            if name in by_name:
                by_name[name].pop(flag, None)
    if key in operation.unset:
        for element in elements:
            element.pop(flag, None)
    return violations


def expand_array_keys(  # noqa: C901
    operation: Operation, table: DocumentTable, current: Mapping[str, Any] | None, *, index: int
) -> Operation:
    """列名が `[]`・`[{キー}]` を含む共通のキーへの操作を、オブジェクトの配列の列の置き換えにした操作を返す。"""
    all_keys, selected_keys = _array_keys(table.metadata)
    collected = set(all_keys) | set(selected_keys)
    if not collected:
        return operation
    data = operation.data or {}
    used = (
        set(operation.set)
        | set(operation.add_to)
        | set(operation.remove_from)
        | set(operation.unset)
        | set(data)
    ) & collected
    violations = [
        Violation(
            path=f"operations[{index}].text_edits[{number}].field",
            rule=f"{edit.field} は文字列の項目ではありません",
        )
        for number, edit in enumerate(operation.text_edits)
        if edit.field in collected
    ]
    # 集めたキーの値が名前（文字列）の配列でなければ、操作を当てる前に違反にする
    for field, values in (
        ("data", data),
        ("set", operation.set),
        ("add_to", operation.add_to),
        ("remove_from", operation.remove_from),
    ):
        violations.extend(
            Violation(
                path=f"operations[{index}].{field}.{key}",
                rule=f"{key} は名前（文字列）の配列で指定します",
            )
            for key, value in values.items()
            if key in collected
            and not (isinstance(value, list) and all(isinstance(name, str) for name in value))
        )
    if violations:
        raise InvalidArgumentError(
            message=f"引数が正しくありません: {len(violations)} 件", violations=violations
        )
    arrays: dict[str, list[Any]] = {}
    unset_arrays: set[str] = set()
    for key in sorted(used & set(all_keys), key=list(all_keys).index):
        array, item = all_keys[key]
        elements = arrays.get(array, _original(operation, current, array))
        arrays[array], removed = _apply_all_key(elements, item, key, operation, data)
        if removed:
            unset_arrays.add(array)
    for key in sorted(used & set(selected_keys), key=list(selected_keys).index):
        array, flag, item = selected_keys[key]
        elements = arrays.setdefault(array, _original(operation, current, array))
        label = next(
            (name for name, (other, _) in all_keys.items() if other == array),
            f"{array}[].{item}",
        )
        violations.extend(
            _apply_selected_key(
                elements, (flag, item), key, operation, data, label=label, index=index
            )
        )
    if violations:
        raise InvalidArgumentError(
            message=f"引数が正しくありません: {len(violations)} 件", violations=violations
        )
    if not arrays:
        return operation
    update: dict[str, Any] = {
        "set": {k: v for k, v in operation.set.items() if k not in collected},
        "add_to": {k: v for k, v in operation.add_to.items() if k not in collected},
        "remove_from": {k: v for k, v in operation.remove_from.items() if k not in collected},
        "unset": [k for k in operation.unset if k not in collected],
    }
    if operation.op == "update":
        for array, elements in arrays.items():
            if array in unset_arrays:
                update["unset"].append(array)
            else:
                update["set"][array] = elements
    else:
        rebuilt = {k: copy.deepcopy(v) for k, v in data.items() if k not in collected}
        for array, elements in arrays.items():
            if array not in unset_arrays:
                set_field(rebuilt, array, elements)
        update["data"] = rebuilt
    return operation.model_copy(update=update)

"""項目の操作を当てる。"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from project_index.features.documents.fields import delete_field, get_field, set_field
from project_index.shared.errors import InvalidArgumentError, Violation
from project_index.shared.narrowing import is_dict, is_list

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, MutableMapping

    from project_index.features.sources.types import DocumentTable
    from project_index.features.write.types import Operation, TextEdit


def _merge(target: dict[object, object], value: dict[object, object]) -> None:
    """オブジェクトは今の値へ再帰でマージし、配列とスカラーは置き換える。"""
    for key, item in value.items():
        existing = target.get(key)
        if is_dict(item) and is_dict(existing):
            _merge(existing, item)
        else:
            target[key] = copy.deepcopy(item)


def _set(content: MutableMapping[str, Any], path: str, value: object) -> None:
    """項目のパスへ値を入れる（オブジェクトなら今の値へマージする）。"""
    existing = get_field(content, path)
    if is_dict(value) and is_dict(existing):
        _merge(existing, value)
    else:
        set_field(content, path, copy.deepcopy(value))


def _violation(path: str, rule: str, fix: str = "") -> Violation:
    """操作を当てられない違反 1 件を作る。"""
    return Violation(path=path, rule=rule, fix=fix)


def apply_operation(current: Mapping[str, Any] | None, operation: Operation) -> dict[str, Any]:
    """文書の内容に 1 件の操作を当てた新しい内容を返す。"""
    if operation.op in ("create", "replace"):
        return copy.deepcopy(operation.data or {})
    # 往復編集の内容（CommentedMap）は型を保ったまま複製する
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
    violations.extend(_add_to(content, operation.add_to))
    violations.extend(_remove_from(content, operation.remove_from))
    violations.extend(_text_edits(content, operation.text_edits))
    if violations:
        raise InvalidArgumentError(message="操作を適用できません", violations=violations)
    return content


def _add_to(content: dict[str, Any], add_to: Mapping[str, list[Any]]) -> list[Violation]:
    """配列の項目へ値を追加する（項目が無ければ空の配列を作る）。"""
    violations: list[Violation] = []
    for path, values in add_to.items():
        existing = get_field(content, path)
        if existing is None:
            set_field(content, path, [])
            existing = get_field(content, path)
        if not is_list(existing):
            violations.append(_violation(f"add_to.{path}", "配列ではない項目へは追加できません"))
            continue
        existing.extend(copy.deepcopy(item) for item in values)
    return violations


def _remove_from(content: dict[str, Any], remove_from: Mapping[str, list[Any]]) -> list[Violation]:
    """配列の項目から値を削除する（項目が無ければ何もしない）。"""
    violations: list[Violation] = []
    for path, values in remove_from.items():
        existing = get_field(content, path)
        if existing is None:
            continue
        if not is_list(existing):
            violations.append(
                _violation(f"remove_from.{path}", "配列ではない項目からは削除できません")
            )
            continue
        existing[:] = [item for item in existing if item not in values]
    return violations


def _text_edits(content: dict[str, Any], edits: list[TextEdit]) -> list[Violation]:
    """文字列の項目の一部を置き換える。"""
    violations: list[Violation] = []
    for index, edit in enumerate(edits):
        text = get_field(content, edit.field)
        prefix = f"text_edits[{index}]"
        if not isinstance(text, str):
            violations.append(
                _violation(f"{prefix}.field", "文字列ではない項目は置き換えられません")
            )
            continue
        count = text.count(edit.old) if edit.old else 0
        # 一致が無いか、replace_all を付けずに複数に一致した: 置き換える箇所が決まらない
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
    return violations


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
        update["data"] = _data_to_columns(operation.data, metadata)
    return operation.model_copy(update=update)


def _data_to_columns(data: Mapping[str, Any], metadata: Mapping[str, str]) -> dict[str, Any]:
    """`data` の共通のキーを列名のパスへ書き直した内容を返す。"""
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key in metadata:
            set_field(result, metadata[key], copy.deepcopy(value))
        else:
            result[key] = copy.deepcopy(value)
    return result


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


def _original(
    operation: Operation, current: Mapping[str, Any] | None, array: str
) -> list[dict[object, object]]:
    """書き戻す前の配列の複製（`update` は今の内容、`create`・`replace` は `data` の列名の値）。"""
    source = current if operation.op == "update" else operation.data
    value = get_field(source, array) if source is not None else None
    if not is_list(value):
        return []
    elements = [item for item in value if is_dict(item)]
    if len(elements) != len(value):
        return []
    return copy.deepcopy(elements)


def _rebuild(
    elements: list[dict[object, object]], item: str, names: Iterable[object]
) -> list[dict[object, object]]:
    """渡した名前の並びで配列を作り直す（元からあった名前の要素は他のキーを保つ）。"""
    by_name = {element.get(item): element for element in elements}
    return [by_name.get(name, {item: name}) for name in names]


def _apply_all_key(
    elements: list[dict[object, object]],
    item: str,
    key: str,
    operation: Operation,
    data: Mapping[str, Any],
) -> tuple[list[dict[object, object]], bool]:
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


def _mark(elements: list[dict[object, object]], flag: str, item: str, chosen: set[object]) -> None:
    """選んだ名前の要素だけに真偽値のキーを立て、他の要素からは削除する。"""
    for element in elements:
        if element.get(item) in chosen:
            element[flag] = True
        else:
            element.pop(flag, None)


def _known(
    names: Iterable[object], by_name: Mapping[object, object], where: str, problem: _Problem
) -> tuple[list[object], list[Violation]]:
    """配列にある名前と、配列に無い名前の違反を返す。"""
    found: list[object] = []
    violations: list[Violation] = []
    for name in names:
        if name in by_name:
            found.append(name)
        else:
            violations.append(
                Violation(
                    path=f"operations[{problem.index}].{where}.{problem.key}",
                    rule=f"{name} は {problem.label} にありません",
                )
            )
    return found, violations


@dataclass(frozen=True)
class _Problem:
    """選んだ要素のキーの違反に記載する、操作の位置・キー・配列の名前。"""

    index: int
    key: str
    label: str


def _apply_selected_key(
    elements: list[dict[object, object]],
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
    problem = _Problem(index=index, key=key, label=label)
    violations: list[Violation] = []
    # data・set は渡した名前の要素だけを選び直す
    for where, values in (("data", data), ("set", operation.set)):
        if key in values:
            chosen, missing = _known(values[key], by_name, where, problem)
            violations.extend(missing)
            _mark(elements, flag, item, set(chosen))
    if key in operation.add_to:
        chosen, missing = _known(operation.add_to[key], by_name, "add_to", problem)
        violations.extend(missing)
        for name in chosen:
            by_name[name][flag] = True
    if key in operation.remove_from:
        for name in operation.remove_from[key]:
            if name in by_name:
                by_name[name].pop(flag, None)
    if key in operation.unset:
        _mark(elements, flag, item, set())
    return violations


def _name_violations(
    operation: Operation, data: Mapping[str, Any], collected: set[str], *, index: int
) -> list[Violation]:
    """集めたキーへの文字列の置き換えと、名前（文字列）の配列でない値を違反にする。"""
    violations = [
        Violation(
            path=f"operations[{index}].text_edits[{number}].field",
            rule=f"{edit.field} は文字列の項目ではありません",
        )
        for number, edit in enumerate(operation.text_edits)
        if edit.field in collected
    ]
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
            if key in collected and not _is_names(value)
        )
    return violations


def _is_names(value: object) -> bool:
    """値が名前（文字列）の配列か。"""
    return is_list(value) and all(isinstance(name, str) for name in value)


def _raise_if(violations: list[Violation]) -> None:
    """違反があれば `InvalidArgumentError` を送る。"""
    if violations:
        raise InvalidArgumentError(
            message=f"引数が正しくありません: {len(violations)} 件", violations=violations
        )


def expand_array_keys(
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
    # 集めたキーの値が名前（文字列）の配列でなければ、操作を当てる前に違反にする
    _raise_if(_name_violations(operation, data, collected, index=index))
    arrays: dict[str, list[dict[object, object]]] = {}
    unset_arrays: set[str] = set()
    for key in sorted(used & set(all_keys), key=list(all_keys).index):
        array, item = all_keys[key]
        elements = arrays.get(array, _original(operation, current, array))
        arrays[array], removed = _apply_all_key(elements, item, key, operation, data)
        if removed:
            unset_arrays.add(array)
    violations: list[Violation] = []
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
    _raise_if(violations)
    if not arrays:
        return operation
    return operation.model_copy(
        update=_array_update(operation, data, collected, arrays, unset_arrays)
    )


def _array_update(
    operation: Operation,
    data: Mapping[str, Any],
    collected: set[str],
    arrays: dict[str, list[dict[object, object]]],
    unset_arrays: set[str],
) -> dict[str, Any]:
    """集めたキーを除いた操作に、書き戻した配列の列の置き換えを足した更新を作る。"""
    update_set = _without(operation.set, collected)
    unset = [k for k in operation.unset if k not in collected]
    update: dict[str, Any] = {
        "set": update_set,
        "add_to": _without(operation.add_to, collected),
        "remove_from": _without(operation.remove_from, collected),
        "unset": unset,
    }
    kept = {array: elements for array, elements in arrays.items() if array not in unset_arrays}
    # update は列の置き換えか削除、create・replace は data へ書き戻す
    if operation.op == "update":
        unset.extend(array for array in arrays if array in unset_arrays)
        update_set.update(kept)
        return update
    rebuilt = copy.deepcopy(_without(data, collected))
    for array, elements in kept.items():
        set_field(rebuilt, array, elements)
    update["data"] = rebuilt
    return update


def _without[V](values: Mapping[str, V], keys: set[str]) -> dict[str, V]:
    """`keys` のキーを除いた辞書を返す。"""
    return {key: value for key, value in values.items() if key not in keys}

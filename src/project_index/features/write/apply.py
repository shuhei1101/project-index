"""項目の操作を当てる。"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from project_index.features.documents.fields import (
    ANY_DEPTH_PREFIX,
    REF_PATH_PREFIX,
    delete_field,
    get_field,
    resolve_array,
    resolve_ref_path,
    set_field,
    set_field_at,
)
from project_index.shared.errors import InvalidArgumentError, Violation
from project_index.shared.narrowing import is_dict, is_list

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, MutableMapping

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


# 本文のファイルの内容を受けるキー（`data`・`set` のキーと `text_edits[].field`）
BODY_KEY = "@body"


def _violation(path: str, rule: str, fix: str = "") -> Violation:
    """操作を当てられない違反 1 件を作る。"""
    return Violation(path=path, rule=rule, fix=fix)


def apply_operation(
    current: Mapping[str, Any] | None,
    operation: Operation,
    *,
    schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """文書の内容に 1 件の操作を当てた新しい内容を返す。"""
    # 本文は要素に当てない（本文の適用が当てる）
    if operation.op in ("create", "replace"):
        data = {key: value for key, value in (operation.data or {}).items() if key != BODY_KEY}
        return copy.deepcopy(data)
    # 往復編集の内容（CommentedMap）は型を保ったまま複製する
    content = cast("dict[str, Any]", copy.deepcopy(current if current is not None else {}))
    violations: list[Violation] = []
    for path, value in operation.set.items():
        if path == BODY_KEY:
            continue
        try:
            _set(content, path, value)
        except InvalidArgumentError as error:
            violations.extend(
                _violation(f"set.{path}", violation.rule) for violation in error.violations
            )
    violations.extend(_unset(content, operation.unset, schema))
    violations.extend(_add_to(content, operation.add_to, schema))
    violations.extend(_remove_from(content, operation.remove_from, schema))
    violations.extend(_text_edits(content, operation.text_edits, schema))
    if violations:
        raise InvalidArgumentError(message="操作を適用できません", violations=violations)
    return content


def _unset(
    content: dict[str, Any], unset: Iterable[str], schema: Mapping[str, Any] | None
) -> list[Violation]:
    """項目を削除する（無い項目は飛ばす）。"""
    violations: list[Violation] = []
    for path in unset:
        try:
            delete_field(content, path, schema=schema)
        except InvalidArgumentError as error:
            # 要素の選び方を含む・`#` で始まるパスを解けない: 理由を `unset.{要素}` の違反にする
            violations.extend(_violation(f"unset.{path}", item.rule) for item in error.violations)
    return violations


def _add_to(
    content: dict[str, Any], add_to: Mapping[str, list[Any]], schema: Mapping[str, Any] | None
) -> list[Violation]:
    """配列の項目へ値を追加する（`#` で始まらないキーの項目が無ければ空の配列を作る）。"""
    violations: list[Violation] = []
    for path, values in add_to.items():
        try:
            existing = resolve_array(content, schema or {}, path, create=True)
        except InvalidArgumentError as error:
            violations.extend(_violation(f"add_to.{path}", item.rule) for item in error.violations)
            continue
        if not is_list(existing):
            violations.append(_violation(f"add_to.{path}", "配列ではない項目へは追加できません"))
            continue
        existing.extend(copy.deepcopy(item) for item in values)
    return violations


def _remove_from(
    content: dict[str, Any],
    remove_from: Mapping[str, list[Any]],
    schema: Mapping[str, Any] | None,
) -> list[Violation]:
    """配列の項目から値を削除する（項目が無ければ何もしない）。"""
    violations: list[Violation] = []
    for path, values in remove_from.items():
        try:
            existing = resolve_array(content, schema or {}, path, create=False)
        except InvalidArgumentError as error:
            violations.extend(
                _violation(f"remove_from.{path}", item.rule) for item in error.violations
            )
            continue
        if existing is None:
            continue
        if not is_list(existing):
            violations.append(
                _violation(f"remove_from.{path}", "配列ではない項目からは削除できません")
            )
            continue
        existing[:] = [item for item in existing if item not in values]
    return violations


def _text_edits(
    content: dict[str, Any], edits: list[TextEdit], schema: Mapping[str, Any] | None
) -> list[Violation]:
    """文字列の項目の一部を置き換える。"""
    violations: list[Violation] = []
    for index, edit in enumerate(edits):
        if edit.field == BODY_KEY:
            continue
        prefix = f"text_edits[{index}]"
        try:
            text, write = _edit_target(content, edit.field, schema)
        except InvalidArgumentError as error:
            violations.extend(_violation(f"{prefix}.field", item.rule) for item in error.violations)
            continue
        if not isinstance(text, str):
            violations.append(
                _violation(f"{prefix}.field", "文字列ではない項目は置き換えられません")
            )
            continue
        mismatch = _old_violation(text, edit, prefix)
        if mismatch is not None:
            violations.append(mismatch)
            continue
        write(text.replace(edit.old, edit.new))
    return violations


def _old_violation(text: str, edit: TextEdit, prefix: str) -> Violation | None:
    """`old` の一致が置き換える箇所を決められない場合の違反を返す。"""
    count = text.count(edit.old) if edit.old else 0
    # 一致が無いか、replace_all を付けずに複数に一致した: 置き換える箇所が決まらない
    if count == 0 or (count > 1 and not edit.replace_all):
        return _violation(
            f"{prefix}.old",
            f"old の一致が {count} か所です",
            f"一致が 1 か所になるよう前後の文字を含めるか、replace_all を true にしてください"
            f"（一致 {count} 件）",
        )
    return None


def _edit_target(
    content: dict[str, Any], field: str, schema: Mapping[str, Any] | None
) -> tuple[object, Callable[[str], None]]:
    """置き換える項目の今の値と、新しい値を書く関数を返す。"""
    # `#` で始まらない項目のパスは、今までどおり項目のパスで読み書きする
    if not field.startswith(REF_PATH_PREFIX):
        return get_field(content, field), lambda text: set_field(content, field, text)
    tokens = resolve_ref_path(content, schema or {}, field[len(REF_PATH_PREFIX) :])
    return _value_at(content, tokens), lambda text: set_field_at(content, tokens, text)


def _value_at(content: Mapping[str, Any], tokens: list[str | int]) -> object:
    """解いた並びで指した値を返す（解いた並びは必ずたどれる）。"""
    current: Any = content
    for token in tokens:
        current = current[token]
    return current


def apply_body(current_body: str | None, operation: Operation, *, index: int) -> str | None:
    """操作の `@body` を本文に当てて、新しい本文を返す（本文を変えない操作は `None`）。"""
    item, given = (
        ("data", operation.data or {})
        if operation.op in ("create", "replace")
        else ("set", operation.set)
    )
    if BODY_KEY in given and not isinstance(given[BODY_KEY], str):
        raise InvalidArgumentError(
            message="操作を適用できません",
            violations=[
                _violation(
                    f"operations[{index}].{item}.{BODY_KEY}",
                    f"{BODY_KEY} は文字列で指定します",
                    "本文の全体を文字列で指定してください",
                )
            ],
        )
    if item == "data":
        return given.get(BODY_KEY)
    edits = [(n, edit) for n, edit in enumerate(operation.text_edits) if edit.field == BODY_KEY]
    if BODY_KEY not in given and not edits:
        return None
    return _edit_body(given.get(BODY_KEY, current_body or ""), edits, index=index)


def _edit_body(body: str, edits: list[tuple[int, TextEdit]], *, index: int) -> str:
    """本文に `text_edits` を順に当てる（一致の判定は項目の `text_edits` と同じ）。"""
    violations: list[Violation] = []
    for n, edit in edits:
        count = body.count(edit.old) if edit.old else 0
        # 一致が無いか、replace_all を付けずに複数に一致した: 置き換える箇所が決まらない
        if count == 0 or (count > 1 and not edit.replace_all):
            violations.append(
                _violation(
                    f"operations[{index}].text_edits[{n}].old",
                    f"old の一致が {count} か所です",
                    f"一致が 1 か所になるよう前後の文字を含めるか、replace_all を true にしてください"
                    f"（一致 {count} 件）",
                )
            )
            continue
        body = body.replace(edit.old, edit.new)
    if violations:
        raise InvalidArgumentError(message="操作を適用できません", violations=violations)
    return body


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
        # `**.` の列名はどの深さの列もまとめるキーで、配列の要素へ書き戻さない
        if column.startswith(ANY_DEPTH_PREFIX):
            continue
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


def _head_key(path: str) -> str:
    """項目のパスの先頭のキー。"""
    return re.split(r"[.\[]", path, maxsplit=1)[0]


def _any_depth_violations(
    operation: Operation, metadata: Mapping[str, str], *, index: int
) -> list[Violation]:
    """列名が `**.` で始まる共通のキーへの操作を違反にする。"""
    columns = {
        key: column for key, column in metadata.items() if column.startswith(ANY_DEPTH_PREFIX)
    }
    if not columns:
        return []
    targets: list[tuple[str, str]] = [
        (f"operations[{index}].{field}.{path}", path)
        for field, values in (
            ("data", operation.data or {}),
            ("set", operation.set),
            ("add_to", operation.add_to),
            ("remove_from", operation.remove_from),
        )
        for path in values
    ]
    targets += [(f"operations[{index}].unset", path) for path in operation.unset]
    targets += [
        (f"operations[{index}].text_edits[{number}].field", edit.field)
        for number, edit in enumerate(operation.text_edits)
    ]
    return [
        Violation(
            path=where,
            rule=(f"{key} は文書の中の複数の列（{columns[key]}）をまとめたキーで、書き込めません"),
            fix="列名の項目のパス（`refs`・`functions[0].refs` など）で指定してください",
        )
        for where, path in targets
        if (key := _head_key(path)) in columns
    ]


def expand_array_keys(
    operation: Operation, table: DocumentTable, current: Mapping[str, Any] | None, *, index: int
) -> Operation:
    """列名が `[]`・`[{キー}]` を含む共通のキーへの操作を、オブジェクトの配列の列の置き換えにした操作を返す。"""
    # どの深さの列もまとめるキーは、書き込む場所を 1 つに決められない
    _raise_if(_any_depth_violations(operation, table.metadata, index=index))
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

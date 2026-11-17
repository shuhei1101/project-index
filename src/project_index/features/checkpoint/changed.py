"""確認の時点の読み取りと、中身が変わったファイルの一覧。"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from project_index.features.checkpoint.types import (
    CHECKPOINT_KEY,
    BaseKind,
    ChangedBase,
    ChangedResult,
    Checkpoint,
    FilesYamlNotFoundError,
    ReviewedFile,
)
from project_index.integrations.git import GitError, repo_root, run_git
from project_index.shared.narrowing import is_dict, is_list
from project_index.shared.yaml_io import load_yaml

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

# `git diff --name-status` の改名・複製の状態の頭文字
_RENAME_STATUSES = frozenset({"R", "C"})
_DELETED_STATUS = "D"


def read_checkpoint(data: Mapping[str, object]) -> Checkpoint | None:
    """管理用の YAML の値から `checkpoint` を読む。"""
    value = data.get(CHECKPOINT_KEY)
    if value is None:
        return None
    if not is_dict(value):
        msg = f"{CHECKPOINT_KEY}: マッピング"
        raise ValueError(msg)
    commit = value.get("commit")
    if commit is not None and not isinstance(commit, str):
        msg = "commit: 文字列"
        raise ValueError(msg)
    return Checkpoint(
        commit=commit,
        reviewed=_read_reviewed(value.get("reviewed")),
        checked_at=_read_checked_at(value.get("checked_at")),
    )


def find_changed(root: Path, files_yaml: str) -> ChangedResult:
    """確認の時点の後に中身が変わった、管理用の YAML の行のファイルを返す。"""
    yaml_path = root / files_yaml
    if not yaml_path.is_file():
        raise FilesYamlNotFoundError(yaml_path)
    data = load_yaml(yaml_path.read_text(encoding="utf-8"))
    mapping: dict[str, object] = (
        {str(key): item for key, item in data.items()} if is_dict(data) else {}
    )
    checkpoint = read_checkpoint(mapping)
    rows = _row_paths(mapping, files_yaml)
    in_git = repo_root(root) is not None
    base, missing = _resolve_base(root, files_yaml, yaml_path, checkpoint, in_git=in_git)
    changed = _git_changed(root, base, rows) if in_git else _mtime_changed(root, base, rows)
    reviewed = checkpoint.reviewed if checkpoint is not None else ()
    files = sorted(path for path in changed if not _is_reviewed(root, path, reviewed))
    return ChangedResult(base=base, files=tuple(files), missing_commit=missing)


def _read_reviewed(value: object) -> tuple[ReviewedFile, ...]:
    """`reviewed[]` を見直し済みのファイルの並びにする。"""
    if value is None:
        return ()
    if not is_list(value):
        msg = "reviewed: path と sha256 を持つマッピングの並び"
        raise ValueError(msg)
    reviewed: list[ReviewedFile] = []
    for item in value:
        path = item.get("path") if is_dict(item) else None
        sha256 = item.get("sha256") if is_dict(item) else None
        if not isinstance(path, str) or not isinstance(sha256, str):
            msg = "reviewed: path と sha256 を持つマッピングの並び"
            raise ValueError(msg)
        reviewed.append(ReviewedFile(path=path, sha256=sha256))
    return tuple(reviewed)


def _read_checked_at(value: object) -> datetime | None:
    """`checked_at` をタイムゾーン付きの日時にする。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError as error:
            msg = "checked_at: ISO 8601 の日時"
            raise ValueError(msg) from error
    # タイムゾーンの無い日時は UTC として扱う
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _row_paths(data: Mapping[str, object], files_yaml: str) -> set[str]:
    """管理用の YAML の行の `path` を、`root` からのパスの集合にする。"""
    folder = PurePosixPath(files_yaml).parent
    rows = data.get("files")
    if not is_list(rows):
        return set()
    paths: set[str] = set()
    for row in rows:
        path = row.get("path") if is_dict(row) else None
        if isinstance(path, str):
            paths.add((folder / path).as_posix())
    return paths


def _resolve_base(
    root: Path,
    files_yaml: str,
    yaml_path: Path,
    checkpoint: Checkpoint | None,
    *,
    in_git: bool,
) -> tuple[ChangedBase, str | None]:
    """起点を決め、記録した commit が無かったときはその ID も返す。"""
    missing: str | None = None
    if checkpoint is not None and checkpoint.commit is not None:
        # 記録した commit がリポジトリにあれば、それを起点にする
        if in_git and _commit_exists(root, checkpoint.commit):
            return ChangedBase(BaseKind.CHECKPOINT_COMMIT, checkpoint.commit), None
        # squash merge・rebase で消えた: 記録が無いときと同じ選び方へ進む
        missing = checkpoint.commit
        logger.warning(
            "記録した commit がリポジトリに無いため起点を切り替えた（commit: %s・管理用の YAML: %s）",
            missing,
            yaml_path,
        )
    elif checkpoint is not None and checkpoint.checked_at is not None:
        # 記録した日時があれば、それを起点にする
        return ChangedBase(BaseKind.CHECKPOINT_TIME, checkpoint.checked_at.isoformat()), None
    if in_git:
        output = run_git(["log", "-1", "--format=%H", "--", files_yaml], cwd=root)
        commit = output.strip() if isinstance(output, str) else ""
        # 管理用の YAML が Git で追跡されていれば、最後に変更した commit を起点にする
        if commit:
            return ChangedBase(BaseKind.FILES_YAML_COMMIT, commit), missing
    # 追跡されていない（ローカル運用・Git 管理外）: 管理用の YAML の変更日時を起点にする
    modified = datetime.fromtimestamp(yaml_path.stat().st_mtime, UTC)
    return ChangedBase(BaseKind.FILES_YAML_MTIME, modified.isoformat()), missing


def _commit_exists(root: Path, commit: str) -> bool:
    """commit がリポジトリにあるかを返す。"""
    try:
        run_git(["cat-file", "-e", f"{commit}^{{commit}}"], cwd=root)
    except GitError:
        return False
    return True


def _git_changed(root: Path, base: ChangedBase, rows: set[str]) -> set[str]:
    """起点の commit と作業ツリーの差分から、行のファイルのうち変わったものを返す。"""
    if base.kind in {BaseKind.CHECKPOINT_COMMIT, BaseKind.FILES_YAML_COMMIT}:
        commit = base.value
    else:
        # 起点が日時: committer の日時がそれ以前の最後の commit を起点にする
        output = run_git(["rev-list", "-1", f"--before={base.value}", "HEAD"], cwd=root)
        commit = output.strip() if isinstance(output, str) else ""
        if not commit:
            # 全ての commit が起点より後: 空のツリーと比べる
            empty = run_git(["hash-object", "-t", "tree", "/dev/null"], cwd=root)
            commit = empty.strip() if isinstance(empty, str) else ""
    output = run_git(
        ["diff", "--name-status", "-M", "-z", "--relative", commit, "--", "."], cwd=root
    )
    text = output if isinstance(output, str) else output.decode("utf-8")
    return _changed_rows(text.split("\0"), rows)


def _changed_rows(tokens: list[str], rows: set[str]) -> set[str]:
    """`diff --name-status -z` の出力を、行のファイルのうち変わったものにする。"""
    changed: set[str] = set()
    index = 0
    while index < len(tokens) and tokens[index]:
        status = tokens[index][0]
        if status in _RENAME_STATUSES:
            # 改名: 改名前のパスが行にあれば改名先のパスで出す
            old, new = tokens[index + 1], tokens[index + 2]
            if old in rows:
                changed.add(new)
            index += 3
            continue
        path = tokens[index + 1]
        # 削除は setup の突き合わせが削除の候補にするので出さない
        if status != _DELETED_STATUS and path in rows:
            changed.add(path)
        index += 2
    return changed


def _mtime_changed(root: Path, base: ChangedBase, rows: set[str]) -> set[str]:
    """Git 管理外で、起点の日時より後に変更された行のファイルを返す。"""
    since = datetime.fromisoformat(base.value).timestamp()
    changed: set[str] = set()
    for path in rows:
        target = root / path
        if target.is_file() and target.stat().st_mtime > since:
            changed.add(path)
    return changed


def _is_reviewed(root: Path, path: str, reviewed: tuple[ReviewedFile, ...]) -> bool:
    """見直し済みで、今の中身が記録したハッシュと同じかを返す。"""
    for item in reviewed:
        if item.path == path:
            target = root / path
            return (
                target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == item.sha256
            )
    return False

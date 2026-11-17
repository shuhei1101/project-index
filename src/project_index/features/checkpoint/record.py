"""管理用の YAML への確認の時点の記録。"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from ruamel.yaml.comments import CommentedMap

from project_index.features.checkpoint.types import (
    CHECKPOINT_KEY,
    Checkpoint,
    FilesYamlNotFoundError,
    ReviewedFile,
    ReviewedFileNotFoundError,
)
from project_index.integrations.git import repo_root, run_git
from project_index.shared.files import replace_file
from project_index.shared.yaml_io import dump_roundtrip, load_roundtrip

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path


def record_checkpoint(
    root: Path, files_yaml: str, *, reviewed: Sequence[str] = (), now: datetime
) -> Checkpoint:
    """管理用の YAML の `checkpoint` を今の確認の時点で置き換える。"""
    yaml_path = root / files_yaml
    if not yaml_path.is_file():
        raise FilesYamlNotFoundError(yaml_path)
    # 見直したファイルが無ければ、管理用の YAML を書き換える前に止める
    for path in reviewed:
        if not (root / path).is_file():
            raise ReviewedFileNotFoundError(root / path)
    original = yaml_path.read_text(encoding="utf-8")
    doc = load_roundtrip(original, file=str(yaml_path))
    value = CommentedMap()
    if repo_root(root) is not None:
        # Git の配信元: HEAD の commit と、見直した未 commit のファイルの中身のハッシュ
        output = run_git(["rev-parse", "HEAD"], cwd=root)
        commit = output.strip() if isinstance(output, str) else ""
        files = tuple(
            ReviewedFile(path=path, sha256=hashlib.sha256((root / path).read_bytes()).hexdigest())
            for path in reviewed
        )
        value["commit"] = commit
        value["reviewed"] = [{"path": item.path, "sha256": item.sha256} for item in files]
        checkpoint = Checkpoint(commit=commit, reviewed=files)
    else:
        # Git 管理外: 記録した日時だけを持つ
        value["checked_at"] = now.isoformat()
        checkpoint = Checkpoint(commit=None, checked_at=now)
    doc[CHECKPOINT_KEY] = value
    # 読んだ管理用の YAML の配列の字下げで書く
    replace_file(yaml_path, dump_roundtrip(doc, original=original))
    return checkpoint

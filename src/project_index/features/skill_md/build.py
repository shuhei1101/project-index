"""エージェントフローの読み込み、`type: skill` の SKILL.md の組み立て・書き出しと、書き込む前の検査。"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ruamel.yaml import YAML

from project_index.features.documents.indexable import walk_files
from project_index.features.documents.loader import collect_files
from project_index.features.documents.schema import resolve_schema_refs
from project_index.features.settings.query import config_path, load_terminal_config
from project_index.features.settings.types import TerminalConfigInvalidError
from project_index.features.skill_md.types import (
    AgentFlowFile,
    InvalidAgentFlowError,
    Problem,
    SkillFile,
)
from project_index.features.sources.schema_ref import (
    SchemaRef,
    SchemaRefError,
    read_schema_ref,
    terminal_lookup,
)
from project_index.features.sources.service import build_source_config
from project_index.features.validation.rules import check_schema
from project_index.shared.files import replace_file
from project_index.shared.narrowing import is_dict
from project_index.shared.yaml_io import YamlLoadError, load_yaml

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from project_index.features.sources.types import DocumentTable

# 配信元の設定の文書の行のうち、エージェントフローを持つ行の `id`
AGENT_FLOW_KIND = "agent_flow"
# 配信元の直下で読み込む設定のファイル
SOURCE_CONFIG_FILE = "project-index.yaml"
# SKILL.md の frontmatter の後ろに置く 1 行（`{path}` にエージェントフローのパス）
GENERATED_COMMENT = (
    "<!-- {path} から生成した。このファイルを修正せず、設計書を修正して再生成する -->"
)
# 生成元の無い SKILL.md を探すときに照合するファイル名
SKILL_FILE_NAME = "SKILL.md"
# 生成元のコメントの行から `{path}` を取り出す正規表現
_GENERATED_PATTERN = re.compile(
    "^" + re.escape(GENERATED_COMMENT).replace(re.escape("{path}"), "(?P<path>.+?)") + "$",
    re.MULTILINE,
)
# 検査のモードで、配信元に同じ `id` が無い標準入力のパス
STDIN_PATH = "-"
# `ref` の書式（`{エージェントフローの id}#steps[{工程の名前}]`）
_STEP_REF = re.compile(r"^(?P<flow>[^\s#]+)#steps\[(?P<name>.+)\]$")
# `ref` を引いた結果の工程と、引けなかったときの理由
type _Resolved = tuple[dict[str, Any] | None, str, str]


# ---- 読み込み ----


def load_agent_flows(root: Path) -> tuple[list[AgentFlowFile], dict[str, Any]]:
    """配信元の設定の `agent_flow` の行に該当するエージェントフローと、その行のスキーマを読み込む。"""
    table = _agent_flow_table(root)
    schema = _read_schema(root, table)
    flows: list[AgentFlowFile] = []
    problems: list[Problem] = []
    for relative in collect_files(root, table):
        value = _read_yaml_file(root / relative, relative, problems)
        # 読めない・辞書でないファイルは問題に集め、全て読んでから送る
        if value is not None:
            flows.append(AgentFlowFile(path=relative, data=value))
    if problems:
        raise InvalidAgentFlowError(problems)
    return flows, schema


def _agent_flow_table(root: Path) -> DocumentTable:
    """配信元の設定を読み、`agent_flow` の行を返却する。"""
    problems: list[Problem] = []
    value = _read_yaml_file(root / SOURCE_CONFIG_FILE, SOURCE_CONFIG_FILE, problems)
    if value is None:
        raise InvalidAgentFlowError(problems)
    try:
        config = build_source_config(value)
    except (KeyError, TypeError, ValueError) as error:
        # 必須のキーが無い・型が違う配信元の設定
        rule = f"配信元の設定を読み込めません（{error}）"
        raise InvalidAgentFlowError(
            [Problem(file=SOURCE_CONFIG_FILE, path="$", rule=rule)]
        ) from error
    for table in config.documents:
        if table.id == AGENT_FLOW_KIND:
            return table
    rule = f"documents に id が {AGENT_FLOW_KIND} の行がありません"
    raise InvalidAgentFlowError([Problem(file=SOURCE_CONFIG_FILE, path="documents", rule=rule)])


def _read_yaml_file(path: Path, relative: str, problems: list[Problem]) -> dict[str, Any] | None:
    """YAML のファイルを辞書で読む。読めなければ問題を加えて `None` を返却する。"""
    try:
        value = load_yaml(path.read_text(encoding="utf-8"), file=relative)
    except (OSError, UnicodeDecodeError, YamlLoadError) as error:
        problems.append(
            Problem(file=relative, path="$", rule=f"YAML として読み込めません（{error}）")
        )
        return None
    if not is_dict(value):
        problems.append(Problem(file=relative, path="$", rule="最上位が辞書ではありません"))
        return None
    return cast("dict[str, Any]", value)


def _read_schema(root: Path, table: DocumentTable) -> dict[str, Any]:
    """行の `schema` を読み、`$ref` まで解いたスキーマを返却する。"""
    # 配信元の中のファイルを指す行
    if isinstance(table.schema_path, str):
        problems: list[Problem] = []
        path = root / table.schema_path
        raw = _read_yaml_file(path, table.schema_path, problems)
        if raw is None:
            raise InvalidAgentFlowError(problems)
        return resolve_schema_refs(raw, path)
    # SQLite の表の行: スキーマのファイルを持たない
    if table.schema_path is None:
        return {}
    # ほかの配信元のリビジョンのスキーマを指す行
    return _read_ref_schema(table.schema_path)


def _read_ref_schema(ref: SchemaRef) -> dict[str, Any]:
    """端末の設定の `sources` から参照先の配信元を引き、`ref` の commit のスキーマを読む。"""
    label = f"{ref.source}:{ref.path}@{ref.ref}"
    try:
        terminal = load_terminal_config(config_path(os.environ))
        return read_schema_ref(ref, lookup=terminal_lookup(terminal)).schema
    except TerminalConfigInvalidError as error:
        rule = f"端末の設定を読み込めません（{error}）"
        raise InvalidAgentFlowError([Problem(file=label, path="$", rule=rule)]) from error
    except SchemaRefError as error:
        raise InvalidAgentFlowError([Problem(file=label, path="$", rule=error.rule)]) from error


# ---- 組み立て ----


def build_skill_files(
    root: Path, flows: Sequence[AgentFlowFile], *, schema: Mapping[str, Any] | None
) -> list[SkillFile]:
    """全てのエージェントフローをスキーマで検査し、`type: skill` のものごとに SKILL.md を組み立てる。"""
    # スキーマの検査（検査のモードでは `write_docs` が先に済ませているので飛ばす）
    problems = _schema_problems(flows, schema) if schema is not None else []
    invalid = {problem.file for problem in problems}
    by_id = {str(flow.data.get("id")): flow for flow in flows}
    files: list[SkillFile] = []
    for flow in flows:
        # スキーマに合わないものと `type: skill` でないものは組み立てない
        if flow.path in invalid or flow.data.get("type") != "skill":
            continue
        built, flow_problems = _build_one(root, flow, by_id)
        problems.extend(flow_problems)
        if built is not None:
            files.append(built)
    if problems:
        raise InvalidAgentFlowError(problems)
    return sorted(files, key=lambda file: file.path)


def _schema_problems(flows: Sequence[AgentFlowFile], schema: Mapping[str, Any]) -> list[Problem]:
    """全てのエージェントフローをスキーマで検査し、違反を問題にする。"""
    return [
        Problem(file=flow.path, path=violation.path, rule=violation.rule, fix=violation.fix)
        for flow in flows
        for violation in check_schema(flow.data, schema, schema_file=AGENT_FLOW_KIND)
    ]


def _build_one(
    root: Path, flow: AgentFlowFile, by_id: Mapping[str, AgentFlowFile]
) -> tuple[SkillFile | None, list[Problem]]:
    """1 件の `type: skill` の SKILL.md を組み立てる。問題があれば組み立てずに問題を返却する。"""
    skill_path, path_problem = _skill_path(root, flow)
    steps, problems = resolve_steps(flow, by_id)
    # 書き出す先と埋め込む工程の問題は、両方とも報告する
    if path_problem is not None:
        problems.append(path_problem)
    if problems:
        return None, problems
    return SkillFile(path=skill_path, text=render_skill_md(flow, steps)), []


def _skill_path(root: Path, flow: AgentFlowFile) -> tuple[str, Problem | None]:
    """`skill.path` を返却する。無い・配信元の外部を指すときは問題も返却する。"""
    skill = flow.data.get("skill")
    value = skill.get("path") if is_dict(skill) else None
    if not isinstance(value, str) or not value:
        return "", Problem(file=flow.path, path="skill.path", rule="skill.path がありません")
    base = root.resolve()
    target = (base / value).resolve()
    # 解決したパスが配信元の配下に無い（`..` や絶対パスで外へ出る）
    if target != base and base not in target.parents:
        rule = f"配信元の外部を指しています（{value}）"
        return value, Problem(file=flow.path, path="skill.path", rule=rule)
    return target.relative_to(base).as_posix(), None


def resolve_steps(
    flow: AgentFlowFile, by_id: Mapping[str, AgentFlowFile]
) -> tuple[list[dict[str, Any]], list[Problem]]:
    """`ref` を持つ工程を参照先の工程に置き換えた工程の並びを返却する。"""
    steps: list[dict[str, Any]] = []
    problems: list[Problem] = []
    for index, step in enumerate(_list(flow.data.get("steps"))):
        if not is_dict(step):
            continue
        step_map = cast("dict[str, Any]", step)
        ref = step_map.get("ref")
        # `ref` の無い工程はそのまま並べる
        if not isinstance(ref, str):
            steps.append(step_map)
            continue
        resolved, reason, missing_id = _follow_ref(ref, by_id)
        if resolved is None:
            problems.append(
                Problem(
                    file=flow.path, path=f"steps[{index}].ref", rule=reason, missing_id=missing_id
                )
            )
            continue
        steps.append(resolved)
    return steps, problems


def _follow_ref(ref: str, by_id: Mapping[str, AgentFlowFile]) -> _Resolved:
    """`ref` をたどり、`ref` を持たない参照先の工程を返却する。"""
    visited: set[str] = set()
    current = ref
    while True:
        # 同じ工程へ戻った
        if current in visited:
            return None, f"埋め込む工程 {ref} が同じ工程へ戻ります", ""
        visited.add(current)
        target = _find_step(current, by_id)
        if target is None:
            return None, f"埋め込む工程 {ref} がありません", _missing_flow(current, by_id)
        next_ref = target.get("ref")
        # 参照先も `ref` を持つ: さらにたどる
        if isinstance(next_ref, str):
            current = next_ref
            continue
        return target, "", ""


def _missing_flow(ref: str, by_id: Mapping[str, AgentFlowFile]) -> str:
    """`ref` が指すエージェントフローが無ければその `id` を、あれば空を返却する。"""
    matched = _STEP_REF.match(ref)
    if matched is None or matched["flow"] in by_id:
        return ""
    return str(matched["flow"])


def _find_step(ref: str, by_id: Mapping[str, AgentFlowFile]) -> dict[str, Any] | None:
    """`{id}#steps[{name}]` が指す工程を探す。"""
    matched = _STEP_REF.match(ref)
    if matched is None:
        return None
    flow = by_id.get(matched["flow"])
    steps = _list(flow.data.get("steps")) if flow is not None else []
    for step in steps:
        if is_dict(step) and step.get("name") == matched["name"]:
            return cast("dict[str, Any]", step)
    return None


def render_skill_md(flow: AgentFlowFile, steps: Sequence[Mapping[str, Any]]) -> str:
    """`type: skill` のエージェントフローと解いた工程から、SKILL.md の全文を組み立てる。"""
    data = flow.data
    skill = cast("dict[str, Any]", data.get("skill") or {})
    name = str(skill.get("name") or Path(str(skill["path"])).parent.name)
    sections = [GENERATED_COMMENT.format(path=flow.path), f"# {data.get('title') or name}"]
    arguments = _list(skill.get("arguments"))
    if arguments:
        sections.append(_arguments_section(arguments))
    sections.append("## 手順")
    sections.extend(_step_section(step) for step in steps)
    front = _frontmatter(data, skill, name, arguments)
    return f"---\n{front}---\n\n" + "\n\n".join(sections) + "\n"


def _frontmatter(
    data: Mapping[str, Any], skill: Mapping[str, Any], name: str, arguments: list[Any]
) -> str:
    """値の無いキーを除いた frontmatter の YAML を返却する。"""
    front: dict[str, Any] = {"name": name, "description": data.get("summary")}
    if arguments:
        front["argument-hint"] = " ".join(str(argument.get("hint")) for argument in arguments)
        front["arguments"] = [str(argument.get("name")) for argument in arguments]
    allowed = _list(skill.get("allowed_tools"))
    if allowed:
        front["allowed-tools"] = allowed
    extra = skill.get("frontmatter")
    if is_dict(extra):
        front.update(cast("dict[str, Any]", extra))
    return _dump({key: value for key, value in front.items() if value not in (None, "", [])})


def _arguments_section(arguments: list[Any]) -> str:
    """`## 引数` の表を返却する。"""
    rows = [
        f"| `${argument.get('name')}` | {argument.get('description')} |" for argument in arguments
    ]
    return "\n".join(["## 引数", "", "| 引数 | 説明 |", "| --- | --- |", *rows])


def _step_section(step: Mapping[str, Any]) -> str:
    """工程の `### {name}` のセクションを返却する。"""
    parts = [f"### {step.get('name')}"]
    when = step.get("when")
    if when:
        parts.append(f"{when}だけ行う。")
    body = step.get("body")
    if body:
        parts.append(str(body).rstrip("\n"))
    calls = _list(step.get("calls"))
    if calls:
        parts.append("呼ぶもの:\n\n" + "\n".join(f"- {_call_line(call)}" for call in calls))
    return "\n\n".join(parts)


def _call_line(call: Mapping[str, Any]) -> str:
    """呼ぶもの 1 件を 1 行にする。"""
    kind = call.get("type")
    match kind:
        case "tool":
            line = f"ツール `{call.get('tool')}`"
        case "mcp":
            line = f"MCP `{call.get('server')}` の `{call.get('tool')}`"
        case "command":
            line = f"コマンド `{call.get('command')}`"
        case "skill":
            line = f"スキル `{call.get('skill')}`"
        case "flow":
            line = f"エージェントフロー `{call.get('flow')}`"
        case "agent":
            agent_type = call.get("agent_type") or "general-purpose"
            line = f"サブエージェント `{agent_type}`: {call.get('instruction') or call.get('flow')}"
        case _:
            line = f"`{kind}`"
    args = call.get("args")
    # 引数の制約は 1 行のフロースタイルの YAML で添える
    if is_dict(args):
        line += f" `{_dump(cast('dict[str, Any]', args), flow=True).strip()}`"
    return line


def _list(value: object) -> list[Any]:
    """配列ならそのまま、それ以外は空の配列を返却する。"""
    return cast("list[Any]", value) if isinstance(value, list) else []


def _dump(value: dict[str, Any], *, flow: bool = False) -> str:
    """辞書をキーの並びのまま YAML にする。"""
    yaml = YAML(typ="safe", pure=True)
    yaml.default_flow_style = flow
    yaml.allow_unicode = True
    yaml.width = 4096
    yaml.sort_base_mapping_type_on_output = False  # type: ignore[assignment]
    stream = io.StringIO()
    yaml.dump(value, stream)
    return stream.getvalue()


# ---- 書き出し ----


def write_changed(root: Path, files: Sequence[SkillFile]) -> list[str]:
    """今のファイルと中身が違う SKILL.md だけを書き出し、書き換えたパスを返却する。"""
    written: list[str] = []
    for file in files:
        path = root / file.path
        new = file.text.encode("utf-8")
        # 同じバイト列なら書き換えない（更新時刻も変えない）
        if path.is_file() and path.read_bytes() == new:
            continue
        replace_file(path, file.text)
        written.append(file.path)
    return sorted(written)


def remove_orphans(root: Path, files: Sequence[SkillFile]) -> list[str]:
    """生成元のコメントが `agent_flow` の行を指し、組み立てたどの SKILL.md でもないファイルを削除する。"""
    table = _agent_flow_table(root)
    built = {file.path for file in files}
    removed: list[str] = []
    for relative in walk_files(root):
        *folders, name = relative.split("/")
        # SKILL.md 以外・`.` で始まるフォルダの配下・今回組み立てたものは対象にしない
        if name != SKILL_FILE_NAME or relative in built:
            continue
        if any(folder.startswith(".") for folder in folders):
            continue
        source = _generated_source(root / relative)
        # 生成元のコメントが無い・エージェントフローの行の外を指すファイルは残す
        if source is None or not table.matches(source):
            continue
        (root / relative).unlink()
        removed.append(relative)
    return sorted(removed)


def _generated_source(path: Path) -> str | None:
    """SKILL.md の生成元のコメントが指すパスを返却する（無ければ `None`）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return None
    match = _GENERATED_PATTERN.search(text)
    return match.group("path") if match else None


# ---- 書き込む前の検査 ----


def check_replacement(root: Path, text: str) -> list[Problem]:
    """標準入力のエージェントフローで配信元の同じ `id` を置き換えて組み立て、問題を返却する。"""
    try:
        value = load_yaml(text, file=STDIN_PATH)
    except YamlLoadError as error:
        return [Problem(file=STDIN_PATH, path="$", rule=f"YAML として読み込めません（{error}）")]
    if not is_dict(value):
        return [Problem(file=STDIN_PATH, path="$", rule="最上位が辞書ではありません")]
    incoming = cast("dict[str, Any]", value)
    stdin_path = STDIN_PATH
    try:
        flows, _ = load_agent_flows(root)
        replaced: list[AgentFlowFile] = []
        for flow in flows:
            # 標準入力と同じ `id` のエージェントフローを書き込む前の中身に置き換える
            if flow.data.get("id") == incoming.get("id"):
                stdin_path = flow.path
                replaced.append(AgentFlowFile(path=flow.path, data=incoming))
            else:
                replaced.append(flow)
        if stdin_path == STDIN_PATH:
            replaced.append(AgentFlowFile(path=STDIN_PATH, data=incoming))
        build_skill_files(root, replaced, schema=None)
    except InvalidAgentFlowError as error:
        return _for_stdin(error.problems, stdin_path)
    return []


def check_deletion(root: Path, text: str, delete_ids: Sequence[str]) -> list[Problem]:
    """削除する文書を除いた配信元で、標準入力の文書を指す `ref` が解決できなくなるスキルを返却する。"""
    try:
        value = load_yaml(text, file=STDIN_PATH)
    except YamlLoadError as error:
        return [Problem(file=STDIN_PATH, path="$", rule=f"YAML として読み込めません（{error}）")]
    if not is_dict(value) or not isinstance(value.get("id"), str):
        return [Problem(file=STDIN_PATH, path="$", rule="最上位が id を持つ辞書ではありません")]
    deleted_id = cast("str", value["id"])
    removed = set(delete_ids) or {deleted_id}
    try:
        flows, _ = load_agent_flows(root)
    except InvalidAgentFlowError as error:
        return _for_stdin(error.problems, STDIN_PATH)
    # 削除する文書を除いた残りだけで工程をたどる
    remaining = {
        cast("str", flow.data.get("id")): flow
        for flow in flows
        if flow.data.get("id") not in removed
    }
    problems: list[Problem] = []
    for flow in remaining.values():
        if flow.data.get("type") != "skill":
            continue
        _, found = resolve_steps(flow, remaining)
        # 最初に見つからないのが標準入力の文書の `ref` だけを違反にする
        for problem in found:
            if problem.missing_id != deleted_id:
                continue
            rule = f"{flow.path}（id: {flow.data.get('id')}）: {problem.path}: {problem.rule}"
            problems.append(Problem(file=flow.path, path="$", rule=rule))
    return problems


def _for_stdin(problems: Sequence[Problem], stdin_path: str) -> list[Problem]:
    """標準入力のもの以外の問題を、ファイル全体（`$`）の違反にしてファイルのパスを理由に入れる。"""
    converted: list[Problem] = []
    for problem in problems:
        if problem.file == stdin_path:
            converted.append(problem)
        else:
            converted.append(
                Problem(file=problem.file, path="$", rule=problem.line(), fix=problem.fix)
            )
    return converted

"""サーバーが起動のときに読むプロンプトの YAML の検査と描画（画面用のマーカーは付けない）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jinja2
from pydantic import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from project_index.features.prompt_doc.render import (
    CompiledPart,
    build_environment,
    compile_parts,
    render_example,
)
from project_index.features.prompt_doc.types import PromptDoc, PromptInvalidError, PromptProblem
from project_index.shared.narrowing import is_dict
from project_index.shared.schema_check import format_path, schema_violations
from project_index.shared.yaml_io import YamlLoadError, load_yaml

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from project_index.shared.errors import Violation

# 読むフォルダを `DEFAULT_PROMPTS_DIR` から差し替える環境変数
PROMPTS_DIR_ENV = "PROJECT_INDEX_PROMPTS_DIR"
# クローンの直下の `content/prompts`
DEFAULT_PROMPTS_DIR = Path(__file__).resolve().parents[4] / "content" / "prompts"
# プロンプトの YAML を検査するスキーマ（knowledge の `schemas/prompt.schema.yaml` のコピー）
PROMPT_SCHEMA_PATH = Path(__file__).resolve().parents[4] / "templates" / "prompt.schema.yaml"
# プロンプトのスキーマが `$ref` で指す共通の型（knowledge の `schemas/common.schema.yaml` のコピー）
COMMON_SCHEMA_PATH = PROMPT_SCHEMA_PATH.with_name("common.schema.yaml")
# ファイル全体の違反のキーのパス
WHOLE_FILE_PATH = "$"
# 必須のキー・知らないキーの違反の決まり（理由にキーの名前を添える）
KEY_RULES = ("必須のキーが無い", "知らないキー")


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadedPrompt:
    """検査を通したプロンプト 1 件と部品のテンプレート。"""

    doc: PromptDoc
    compiled: dict[str, CompiledPart]


@dataclass(frozen=True, slots=True, kw_only=True)
class PromptSet:
    """起動のときに読んだプロンプトを ID で引いて描画する（読み直さない）。"""

    prompts: dict[str, LoadedPrompt]
    env: jinja2.Environment

    def render(self, prompt_id: str, values: Mapping[str, Any] | None = None) -> str:
        """ID のプロンプトを変数の値で描画して 1 つの文にする。"""
        loaded = self.prompts[prompt_id]
        doc = loaded.doc
        # 渡されなかった変数は None にする（StrictUndefined で落とさない）
        filled: dict[str, Any] = {name: None for name in doc.vars}
        filled.update(values or {})
        rendered: list[str] = []
        for part in doc.parts:
            compiled = loaded.compiled[part.id]
            # when が偽: 使わない
            if compiled.when is not None and not compiled.when(**filled):
                continue
            template = compiled.texts.get(doc.lang)
            # 注入する言語の本文が無い: 使わない
            if template is None:
                continue
            rendered.append(template.render(**filled))
        return "".join(rendered).rstrip("\n")


def prompts_dir(env: Mapping[str, str]) -> Path:
    """読むフォルダを決める。"""
    value = env.get(PROMPTS_DIR_ENV)
    return Path(value).resolve() if value else DEFAULT_PROMPTS_DIR


def _schema_registry() -> Registry[Any]:
    """プロンプトのスキーマが `$ref` で指す共通の型を解決する登録簿を作る。"""
    common = load_yaml(COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))
    resource: Resource[Any] = Resource.from_contents(common, default_specification=DRAFT202012)
    empty: Registry[Any] = Registry()
    registry: Registry[Any] = empty.with_resource(COMMON_SCHEMA_PATH.name, resource)
    return registry


def _schema_reason(violation: Violation) -> str:
    """スキーマの違反の理由にする（キーの違反はキーの名前を添える）。"""
    if violation.rule in KEY_RULES:
        key = violation.path.rsplit(".", 1)[-1]
        return f"{violation.rule}: `{key}`"
    return violation.rule


def _check_file(
    file: Path,
    *,
    directory: Path,
    schema: object,
    registry: Registry[Any],
    env: jinja2.Environment,
) -> tuple[LoadedPrompt | None, list[PromptProblem]]:
    """プロンプトの YAML 1 枚を読んで検査する（違反があれば先の検査を飛ばす）。"""

    def problem(path: str, reason: str) -> PromptProblem:
        return PromptProblem(file=file, path=path, reason=reason)

    # YAML として読む
    try:
        value = load_yaml(file.read_text(encoding="utf-8"), file=str(file))
    except (OSError, YamlLoadError) as error:
        return None, [problem(WHOLE_FILE_PATH, str(error))]
    # スキーマで検査する
    violations = schema_violations(schema, value, registry=registry)
    if violations:
        return None, [problem(item.path, _schema_reason(item)) for item in violations]
    # id がフォルダからのパスと同じか
    expected_id = file.relative_to(directory).with_suffix("").as_posix()
    if not is_dict(value) or value.get("id") != expected_id:
        return None, [problem("id", f"ファイルのパス {expected_id} と違います")]
    try:
        doc = PromptDoc.model_validate(value)
    except ValidationError as error:
        return None, [
            problem(format_path(item["loc"]) or WHOLE_FILE_PATH, item["msg"])
            for item in error.errors()
        ]
    # 部品をテンプレートにする
    compiled, syntax_errors = compile_parts(doc, env=env)
    if syntax_errors:
        return None, [
            problem(
                f"parts[{item.part_id}].{item.field}",
                f"{item.line} 行目: {item.message}" if item.line is not None else item.message,
            )
            for item in syntax_errors
        ]
    # 変数の example で 1 回描画する
    example = render_example(doc, compiled=compiled, syntax_errors=[], values={}, lang=doc.lang)
    if example.problems:
        return None, [problem("parts", reason) for reason in example.problems]
    return LoadedPrompt(doc=doc, compiled=compiled), []


def load_prompts(directory: Path, *, required: Collection[str]) -> PromptSet:
    """フォルダのプロンプトの YAML を全て読んで検査し、描画できる一式にする。"""
    schema = load_yaml(PROMPT_SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = _schema_registry()
    env = build_environment()
    prompts: dict[str, LoadedPrompt] = {}
    problems: list[PromptProblem] = []
    files = sorted(directory.glob("**/*.yaml")) if directory.is_dir() else []
    for file in files:
        loaded, file_problems = _check_file(
            file, directory=directory, schema=schema, registry=registry, env=env
        )
        problems.extend(file_problems)
        if loaded is not None:
            prompts[file.relative_to(directory).with_suffix("").as_posix()] = loaded
    # 要る ID のうち、ファイルが無いもの
    for prompt_id in required:
        path = directory / f"{prompt_id}.yaml"
        if prompt_id not in prompts and not path.exists():
            problems.append(
                PromptProblem(file=path, path=WHOLE_FILE_PATH, reason="ファイルがありません")
            )
    if problems:
        raise PromptInvalidError(problems)
    return PromptSet(prompts=prompts, env=env)

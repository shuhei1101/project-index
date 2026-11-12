from __future__ import annotations

import html
import io
import re
import sys
from typing import TYPE_CHECKING

from project_index.__main__ import main

if TYPE_CHECKING:
    import pytest

# A-42 の例 2（kind: llm）。言語は en・ja、例の組は no-logs、部品 role の en の本文に <rules> を持つ
REFLECTION_HEAD = """\
id: node/reflection
name: 振り返りのノード
kind: llm
lang: en
description: キャラクターが最近の出来事を振り返り、性格特性の基底値の変化を決める
tags: [reflection]
vars:
  character:
    type: object
    required: true
    description: 振り返るキャラクター
    example: {id: hina, display_name: ひな}
    properties:
      id: {type: string, required: true, description: キャラクターの ID, example: hina}
      display_name: {type: string, required: true, description: 表示名, example: ひな}
  now:
    type: string
    required: true
    description: 今の日時の文
    example: 2026-10-31（金）21:00
  traits:
    type: array
    required: true
    description: 性格特性の定義と今の基底値
    source: DB のキャラクターの性格特性
    example:
      - {name: 好奇心, definition: 新しいものへの興味, base: 0.7}
    items:
      type: object
      description: 性格特性 1 件
      properties:
        name: {type: string, required: true, description: 特性の名前, example: 好奇心}
        definition: {type: string, required: true, description: 特性の定義, example: 新しいものへの興味}
        base: {type: number, required: true, description: 今の基底値（0〜1）, example: 0.7}
  logs:
    type: array
    required: true
    description: 振り返るログの行（古い順）
    example: ["10/31 20:10 コンビニで新作のプリンを買った"]
    items: {type: string, description: ログ 1 行}
output: write_trait_changes を 1 回呼んで終える
"""

REFLECTION_EXAMPLES = """\
examples:
  - id: no-logs
    name: ログが無い
    values: {logs: []}
"""

LOGS_EN_TEXT = """\
      - lang: en
        text: |-
          ### Logs to reflect on (oldest first)
          {% for line in logs -%}
          - {{ line }}
          {% endfor %}
"""

# logs の en の本文の構文を誤らせたもの（{% if %} を閉じない）
LOGS_EN_TEXT_BROKEN = """\
      - lang: en
        text: |-
          ### Logs to reflect on (oldest first)
          {% if logs %}
          - {{ logs }}
"""

# 部品 logs の en の本文は __LOGS_EN__ に差し込む
REFLECTION_PARTS = """\
parts:
  - id: role
    role: system
    tags: [role]
    texts:
      - lang: en
        text: |-
          ### Role
          You are in charge of reflecting on the recent events of "{{ character.display_name }}" (character_id: {{ character.id }}).
          <rules>Decide the changes only from the logs.</rules>
      - lang: ja
        text: |-
          ### 役割
          あなたは、キャラクター「{{ character.display_name }}」（character_id: {{ character.id }}）の振り返りの担当です。
  - id: now
    role: user
    tags: [context]
    texts:
      - lang: en
        text: |-
          ### Now
          {{ now }}
      - lang: ja
        text: |-
          ### いま
          {{ now }}
  - id: traits
    role: user
    tags: [context]
    texts:
      - lang: en
        text: |-
          ### Personality trait definitions and current base values
          {% for t in traits -%}
          - {{ t.name }}: {{ t.definition }} (base {{ t.base }})
          {% endfor %}
      - lang: ja
        text: |-
          ### 性格特性の定義と今の基底値
          {% for t in traits -%}
          - {{ t.name }}: {{ t.definition }}（基底値 {{ t.base }}）
          {% endfor %}
  - id: logs
    role: user
    tags: [context]
    when: "{{ logs | length > 0 }}"
    texts:
__LOGS_EN__      - lang: ja
        text: |-
          ### 振り返るログ（古い順）
          {% for line in logs -%}
          - {{ line }}
          {% endfor %}
  - id: no-logs
    role: user
    tags: [context]
    when: "{{ logs | length == 0 }}"
    texts:
      - lang: en
        text: |-
          ### Logs to reflect on
          - none
      - lang: ja
        text: |-
          ### 振り返るログ
          - なし
"""

REFLECTION_YAML = (
    REFLECTION_HEAD + REFLECTION_EXAMPLES + REFLECTION_PARTS.replace("__LOGS_EN__", LOGS_EN_TEXT)
)

# 例の組 broken（traits に文字列）を加えたもの
REFLECTION_WITH_BROKEN_YAML = (
    REFLECTION_HEAD
    + REFLECTION_EXAMPLES
    + """\
  - id: broken
    name: broken
    values: {traits: oops}
"""
    + REFLECTION_PARTS.replace("__LOGS_EN__", LOGS_EN_TEXT)
)

# 部品 logs の en の本文の構文を誤らせたもの
REFLECTION_SYNTAX_INVALID_YAML = (
    REFLECTION_HEAD
    + REFLECTION_EXAMPLES
    + REFLECTION_PARTS.replace("__LOGS_EN__", LOGS_EN_TEXT_BROKEN)
)

# parts を除いたもの
REFLECTION_WITHOUT_PARTS_YAML = REFLECTION_HEAD + REFLECTION_EXAMPLES

# A-42 の例 1（kind: hook）。言語は ja だけ
SESSION_CONTEXT_HEAD = """\
id: session-context
name: SessionStart の配信元の一覧
kind: hook
lang: ja
description: 作業場所から使える配信元と警告を、セッションの始めに伝える
tags: [sessionstart, 配信元]
vars:
  sources:
    type: array
    required: true
    description: 作業場所から使える配信元
    source: 端末の設定の sources[] のうち scope.read に作業場所が入るもの
    example:
      - {id: claude-balancer, access: read_write, description: 複数のアカウントを貸し出す基盤の設計書}
    items:
      type: object
      description: 配信元 1 件
      properties:
        id: {type: string, required: true, description: 配信元の ID, example: knowledge}
        access: {type: string, required: true, description: 権限, example: read}
        description: {type: string, description: 配信元の説明, example: 共通の規約}
  warnings:
    type: array
    description: 索引の同期のずれ・古い設定などの注意
    example: ["knowledge: 索引が 3 件ずれています"]
    items: {type: string, description: 注意 1 件}
examples:
  - id: no-source
    name: 配信元が無い
    values: {sources: [], warnings: []}
"""

SESSION_CONTEXT_PARTS = """\
parts:
  - id: sources
    when: "{{ sources | length > 0 }}"
    texts:
      - lang: ja
        text: |
          project-index で次の配信元を使えます。
          {% for s in sources %}- {{ s.id }}（{{ s.access }}）: {{ s.description }}
          {% endfor %}
  - id: no-source
    when: "{{ sources | length == 0 }}"
    texts:
      - lang: ja
        text: |
          この作業場所から使える project-index の配信元はありません。
  - id: warnings
    when: "{{ warnings }}"
    texts:
      - lang: ja
        text: |
          注意:
          {% for w in warnings %}- {{ w }}
          {% endfor %}
"""

SESSION_CONTEXT_YAML = SESSION_CONTEXT_HEAD + SESSION_CONTEXT_PARTS

# 配信元 20 件（描画した結果が 1,000 字を超える）の組 many-sources を加えたもの
MANY_SOURCES = ", ".join(
    f"{{id: source-{n:02d}, access: read, description: 端末の設定で読み書きできる配信元の設計書と規約とテンプレートの一式その{n:02d}}}"
    for n in range(1, 21)
)
SESSION_CONTEXT_MANY_SOURCES_YAML = (
    SESSION_CONTEXT_HEAD
    + f"""\
  - id: many-sources
    name: many-sources
    values: {{sources: [{MANY_SOURCES}], warnings: []}}
"""
    + SESSION_CONTEXT_PARTS
)


def _run(monkeypatch: pytest.MonkeyPatch, stdin: str) -> int:
    """標準入力を UTF-8 のバイト列で差し替えて `project-index prompt-doc` を呼ぶ。"""
    monkeypatch.setattr(
        sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin.encode("utf-8")), encoding="utf-8")
    )
    return main(["prompt-doc"])


def _outside_fences(markdown: str) -> str:
    """コードブロックの中の行の頭の `#` を `_` に替え、見出しと読まれないようにする。"""
    lines: list[str] = []
    in_fence = False
    for line in markdown.split("\n"):
        if line.startswith("```"):
            in_fence = not in_fence
        lines.append(line.replace("#", "_", 1) if in_fence and line.startswith("#") else line)
    return "\n".join(lines)


def _until_next(markdown: str, start: int, pattern: re.Pattern[str]) -> str:
    """`start` から、コードブロックの外で `pattern` に当たる位置の前までを返す。"""
    found = pattern.search(_outside_fences(markdown), start + 1)
    return markdown[start : found.start() if found else len(markdown)]


def _section(markdown: str, heading: str) -> str:
    """見出しの行から、次の同じ深さか浅い見出しの前までを返す。"""
    level = heading.split(" ", 1)[0]
    start = markdown.index(f"\n{heading}\n")
    return _until_next(markdown, start, re.compile(rf"\n#{{1,{len(level)}}} "))


def _tab(section: str, lang: str) -> str:
    """セクションの言語のタブの中身を返す。"""
    start = section.index(f"\n#### {lang}\n")
    return _until_next(section, start, re.compile(r"\n#### |\n<!-- /tabs -->"))


def _tab_names(markdown: str) -> list[str]:
    """言語のタブの見出しを出た順に返す。"""
    return re.findall(r"^#### (.+)$", _outside_fences(markdown), flags=re.MULTILINE)


def _pre_text_length(tab: str) -> int:
    """タブの描画結果の `<pre>` の中身を、要素を外してエスケープを戻した字数の合計にする。"""
    bodies = re.findall(r"<pre><code>(.*?)</code></pre>", tab, flags=re.DOTALL)
    return sum(len(html.unescape(re.sub(r"<[^>]+>", "", body))) for body in bodies)


def _char_count(tab: str) -> int:
    """タブの字数の行の字数を返す。"""
    found = re.search(r": ([\d,]+) 字 / 使用しなかった部品", tab)
    assert found is not None
    return int(found.group(1).replace(",", ""))


def test_normal(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """LLM の呼び出しのプロンプト（en・ja）を、変数の表・部品・例の組のセクションにした Markdown を出す（正常系）。"""
    # 実行
    code = _run(monkeypatch, REFLECTION_YAML)
    # 検証
    captured = capsys.readouterr()
    out = captured.out
    default_example = _section(out, "### 既定の例")
    no_logs_example = _section(out, "### ログが無い")
    assert code == 0
    assert captured.err == ""
    # 見出し・バッジ・説明・タグと出力の行
    assert out.startswith("# 振り返りのノード\n")
    assert "`badge:kind: llm` `badge:lang: en`" in out
    assert "キャラクターが最近の出来事を振り返り、性格特性の基底値の変化を決める" in out
    assert "タグ: `badge:reflection`" in out
    assert "出力: write_trait_changes を 1 回呼んで終える" in out
    # 変数の表
    variables = _section(out, "## 変数")
    assert "| 変数 | 型 | 必須 | 例 | 説明 | 出典 |" in variables
    assert "| `character.display_name` | string | ✅ | `ひな` | 表示名 | - |" in variables
    assert "| `traits[].name` | string | ✅ | `好奇心` | 特性の名前 | - |" in variables
    # 部品のセクション
    assert "`badge:role: system` `badge:tag: role`" in _section(out, "### role")
    assert (
        "`badge:role: user` `badge:tag: context` `badge:when: {{ logs | length > 0 }}`"
        in _section(out, "### logs")
    )
    assert (
        '<span data-hint="表示名（型: string、例: ひな）">{{ character.display_name }}</span>'
        in _section(out, "### role")
    )
    # 例の組のセクション
    assert out.index("\n### 既定の例\n") < out.index("\n### ログが無い\n")
    assert "\n### ログが無い\n\n<!-- section: closed -->\n" in out
    assert "**system**" in _tab(default_example, "en")
    assert "**user**" in _tab(default_example, "en")
    assert "注入する本文（en）: " in _tab(default_example, "en")
    assert "使用しなかった部品: no-logs" in _tab(default_example, "en")
    assert "使用しなかった部品: logs" in _tab(no_logs_example, "en")
    assert '<mark data-hint="character.display_name: 表示名">ひな</mark>' in default_example
    # 言語のタブ
    assert "<!-- tabs: group=lang -->" in out
    assert set(_tab_names(out)) == {"en", "ja"}
    assert _tab_names(default_example) == ["en", "ja"]
    # 注意書きが無い
    assert "[!WARNING]" not in out
    assert "[!CAUTION]" not in out
    # 本文のタグのエスケープと、エスケープ前の字数
    assert "&lt;rules&gt;" in _section(out, "### role")
    assert "&lt;rules&gt;" in default_example
    assert "<rules>" not in out
    assert _char_count(_tab(default_example, "en")) == _pre_text_length(_tab(default_example, "en"))


def test_normal_when_single_language(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """言語が ja だけのフックの注入文は、言語のタブを置かずに出す（正常系）。"""
    # 実行
    code = _run(monkeypatch, SESSION_CONTEXT_YAML)
    # 検証
    out = capsys.readouterr().out
    default_example = _section(out, "### 既定の例")
    assert code == 0
    assert "<!-- tabs:" not in out
    assert _tab_names(out) == []
    assert "project-index で次の配信元を使えます。" in _section(out, "### sources")
    assert default_example.count("<pre><code>") == 1
    assert "**" not in default_example
    assert "注入する本文（ja）: " in default_example
    assert "[!WARNING]" not in out


def test_normal_when_example_invalid(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """型の合わない値の組だけを注意書きにし、他の組は描画する（正常系）。"""
    # 実行
    code = _run(monkeypatch, REFLECTION_WITH_BROKEN_YAML)
    # 検証
    out = capsys.readouterr().out
    broken = _section(out, "### broken")
    reason = "`traits` は array ですが、`oops` が入っています"
    assert code == 0
    assert "[!CAUTION]" in _tab(broken, "en")
    assert reason in _tab(broken, "en")
    assert "[!CAUTION]" in _tab(broken, "ja")
    assert reason in _tab(broken, "ja")
    assert "<pre>" not in broken
    assert "[!CAUTION]" not in _section(out, "### 既定の例")
    assert "<pre><code>" in _section(out, "### 既定の例")
    assert "[!CAUTION]" not in _section(out, "### ログが無い")
    assert "<pre><code>" in _section(out, "### ログが無い")
    assert "| `traits[].name` |" in _section(out, "## 変数")
    assert "\n### role\n" in _section(out, "## テンプレート")


def test_normal_when_hook_text_too_long(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """フックの注入文で 1,000 字を超えた組に字数の注意を出す（正常系）。"""
    # 実行
    code = _run(monkeypatch, SESSION_CONTEXT_MANY_SOURCES_YAML)
    # 検証
    out = capsys.readouterr().out
    many_sources = _section(out, "### many-sources")
    assert code == 0
    assert "> [!WARNING]" in many_sources
    assert "上限の 1,000 字を超えています" in many_sources
    assert _char_count(many_sources) > 1000
    assert f"{_char_count(many_sources):,} 字で" in many_sources
    assert "source-20" in many_sources
    assert "<pre><code>" in many_sources
    assert "[!WARNING]" not in _section(out, "### 既定の例")


def test_normal_when_part_syntax_invalid(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Jinja2 の構文が誤った部品だけを注意書きにし、変数の表と他の部品は出す（正常系）。"""
    # 準備
    _run(monkeypatch, REFLECTION_YAML)
    normal = capsys.readouterr().out
    # 実行
    code = _run(monkeypatch, REFLECTION_SYNTAX_INVALID_YAML)
    # 検証
    out = capsys.readouterr().out
    logs = _section(out, "### logs")
    assert code == 0
    assert "[!CAUTION]" in _tab(logs, "en")
    assert "texts[en]（" in _tab(logs, "en")
    assert "行目）の構文が誤っています: " in _tab(logs, "en")
    assert "[!CAUTION]" not in _tab(logs, "ja")
    assert "部品 `logs` の texts[en]（" in _section(out, "### 既定の例")
    assert "[!CAUTION]" in _tab(_section(out, "### 既定の例"), "ja")
    assert "部品 `logs` の texts[en]（" in _section(out, "### ログが無い")
    assert _section(out, "## 変数") == _section(normal, "## 変数")
    assert _section(out, "### role") == _section(normal, "### role")
    assert _section(out, "### now") == _section(normal, "### now")
    assert _section(out, "### traits") == _section(normal, "### traits")
    assert _section(out, "### no-logs") == _section(normal, "### no-logs")


def test_error_when_yaml_unreadable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """読めない YAML は終了コード 1 で終える（異常系）。"""
    # 実行
    code = _run(monkeypatch, "name: [\n")
    # 検証
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "YAML を読み込めません: " in captured.err


def test_error_when_required_key_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`parts` の無いプロンプトは終了コード 1 で終える（異常系）。"""
    # 実行
    code = _run(monkeypatch, REFLECTION_WITHOUT_PARTS_YAML)
    # 検証
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err.startswith("parts: Field required")

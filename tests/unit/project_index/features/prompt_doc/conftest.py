from __future__ import annotations

import pytest

# A-42 の例 2（kind: llm）。言語は en・ja、例の組は no-logs
REFLECTION_YAML = """\
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
examples:
  - id: no-logs
    name: ログが無い
    values: {logs: []}
output: write_trait_changes を 1 回呼んで終える
parts:
  - id: role
    role: system
    tags: [role]
    texts:
      - lang: en
        text: |-
          ### Role
          You are in charge of reflecting on the recent events of "{{ character.display_name }}" (character_id: {{ character.id }}).
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
      - lang: en
        text: |-
          ### Logs to reflect on (oldest first)
          {% for line in logs -%}
          - {{ line }}
          {% endfor %}
      - lang: ja
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

# A-42 の例 1（kind: hook）。言語は ja だけ
SESSION_CONTEXT_YAML = """\
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


@pytest.fixture
def reflection_yaml() -> str:
    """A-42 の例 2（kind: llm）の YAML を返す。"""
    return REFLECTION_YAML


@pytest.fixture
def reflection_without_parts_yaml() -> str:
    """A-42 の例 2 から parts を除いた YAML を返す。"""
    return REFLECTION_YAML.split("parts:\n", 1)[0]


@pytest.fixture
def session_context_yaml() -> str:
    """A-42 の例 1（kind: hook）の YAML を返す。"""
    return SESSION_CONTEXT_YAML

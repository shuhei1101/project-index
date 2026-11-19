"""`POST /_admin/post-write` の本文と応答の型と、通知の文面のプロンプトの ID・ルールの索引のファイル名。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 通知の文面を描画するプロンプト（content/prompts/hooks/post-write-notice.yaml）
NOTICE_PROMPT_ID = "hooks/post-write-notice"
# 配信元のフォルダの直下にあると、文面にルールの索引の 1 行を追加する rule-inject の索引
RULE_INDEX_FILE = "rules.yaml"


class PostWriteRequest(BaseModel):
    """ツール実行後のフックが送信する本文。"""

    # フックの入力に増えたキーを断らないよう、知らないキーは捨てる
    model_config = ConfigDict(extra="ignore")

    session_id: str = Field(description="Claude Code のセッション ID")
    agent_id: str | None = Field(default=None, description="サブエージェントの ID")
    paths: list[str] = Field(min_length=1, description="書き込んだファイルの絶対パス")


class Notice(BaseModel):
    """通知するファイル 1 件の判定。"""

    path: str = Field(description="通知するファイルの絶対パス")
    source: str = Field(description="ファイルを含む配信元の ID")
    action: Literal["add_row", "update_row"] = Field(
        description="管理用の YAML に行が無ければ add_row、あれば update_row"
    )
    files_yaml: str = Field(
        description="行を持つ（持つべき）管理用の YAML の配信元の直下からのパス"
    )


class PostWriteResponse(BaseModel):
    """通知するファイルの判定と、文脈に追加する文面。"""

    notices: list[Notice] = Field(description="今回通知するファイル")
    additional_context: str = Field(description="notices が空なら空文字")

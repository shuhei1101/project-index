# library

採用ライブラリと選定理由の一覧

## 目次

<!-- table: data -->

| ページ | 概要 |
| --- | --- |
| [fastapi](./LIB-1.yaml) | Starlette の上に作られた ASGI の Web フレームワーク。引数の型ヒントからリクエストを検証して受け取る。 |
| [mcp](./LIB-2.yaml) | Model Context Protocol の公式の Python SDK。MCP のサーバーとクライアント、Streamable HTTP のトランスポートを持つ。 |
| [uvicorn](./LIB-3.yaml) | Python の ASGI サーバー。ASGI アプリを HTTP で待ち受ける。 |
| [ruamel.yaml](./LIB-4.yaml) | YAML 1.2 の読み書きのライブラリ。rt モードではコメント・キーの順序・クォートを保ったまま読み書きできる。 |
| [jsonschema](./LIB-5.yaml) | Python の JSON Schema の検証のライブラリ。Draft 2020-12 に対応し、`referencing` でスキーマ間の `$ref` を解決する。 |
| [pydantic](./LIB-6.yaml) | 型ヒントから値の検証と変換を行う Python のデータ検証ライブラリ。 |
| [mdmark](./LIB-7.yaml) | Markdown を検査・描画するライブラリと CLI。project-index は、文書の書き込みで Markdown の値を `mdmark check --text` で点検するためだけに使う。 |
| [jinja2](./LIB-8.yaml) | Python のテンプレートエンジン。`{{ 変数 }}`・`{% if %}`・`{% for %}` の構文で文字列を組み立てる。 |
| [alias-inject](./LIB-9.yaml) | Claude Code のプロンプトに、YAML の文書から集めた用語・文書の別名・コマンドなどのエイリアスを差し込むプラグイン。エイリアスの元の行のスキーマ（`schemas/aliases.schema.yaml`）を正本として持つ。 |

<!-- /table -->

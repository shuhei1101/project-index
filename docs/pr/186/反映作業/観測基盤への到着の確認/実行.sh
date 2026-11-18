#!/bin/bash
set -u

OBS="$HOME/repo/observability"
CMD=(uv run --with-editable "$OBS" pytest tests/unit/)

# 前提確認
if [ $# -gt 1 ] || { [ $# -eq 1 ] && [ "$1" != "--dry-run" ]; }; then
  echo "前提確認: failed"
  echo "受け付ける引数は無しか --dry-run だけ: $*"
  exit 1
fi
if [ ! -d tests/unit ]; then
  echo "前提確認: failed"
  echo "tests/unit が無い（作業ディレクトリが project-index の直下でない）"
  exit 1
fi
if ! grep -q '^observability_test_runs = ' "$OBS/pyproject.toml" 2>/dev/null; then
  echo "前提確認: failed"
  echo "grep '^observability_test_runs = ' $OBS/pyproject.toml"
  exit 1
fi
if ! (exec 3<>/dev/tcp/127.0.0.1/14317) 2>/dev/null; then
  echo "前提確認: failed"
  echo "exec 3<>/dev/tcp/127.0.0.1/14317"
  exit 1
fi
echo "前提確認: ok"

# 計画（--dry-run もここを通る）
echo "実行するコマンド: ${CMD[*]}"
if [ "${1:-}" = "--dry-run" ]; then
  echo "単体テストの実行と送信: changed"
  exit 0
fi

# 適用
BASE=$(mktemp -d)
trap 'rm -rf "$BASE"' EXIT
out=$("${CMD[@]}" --basetemp "$BASE/bt" 2>&1)
code=$?
if [ $code -ne 0 ]; then
  echo "単体テストの実行と送信: failed"
  echo "${CMD[*]} --basetemp $BASE/bt"
  echo "$out" | tail -20
  exit 1
fi
if echo "$out" | grep -q '送信できませんでした'; then
  echo "単体テストの実行と送信: failed"
  echo "${CMD[*]} --basetemp $BASE/bt"
  echo "$out" | grep '送信できませんでした'
  exit 1
fi
echo "$out" | tail -1
echo "単体テストの実行と送信: changed"

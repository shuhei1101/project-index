#!/bin/sh
set -eu

SETTINGS=/home/shuhei2441/.config/dev-docs/settings.yaml
OLD_LINE='    config: /mnt/c/Users/shuhe/repo/project-index/.claude/worktrees/develop/dev-docs.yaml'
NEW_LINE='    config: /mnt/c/Users/shuhe/repo/project-index/.claude/worktrees/develop/project-index.yaml'
NEW_CONFIG=/mnt/c/Users/shuhe/repo/project-index/.claude/worktrees/develop/project-index.yaml
NEW=$(mktemp)
trap 'rm -f "$NEW"' EXIT

# 前提確認
if [ $# -gt 1 ] || { [ $# -eq 1 ] && [ "$1" != "--dry-run" ]; }; then
  echo "前提確認: failed"
  echo "引数: $*"
  exit 1
fi
if [ ! -f "$SETTINGS" ]; then
  echo "前提確認: failed"
  echo "test -f $SETTINGS"
  exit 1
fi
if [ ! -f "$NEW_CONFIG" ]; then
  echo "前提確認: failed"
  echo "test -f $NEW_CONFIG（develop の worktree が改名を取り込んでいない）"
  exit 1
fi
echo "前提確認: ok"

# 計画（--dry-run もここを通る）
if grep -qxF "$NEW_LINE" "$SETTINGS" && ! grep -qxF "$OLD_LINE" "$SETTINGS"; then
  echo "配信元 project-index の config の書き換え: skipped"
  exit 0
fi
COUNT=$(grep -cxF "$OLD_LINE" "$SETTINGS" || true)
if [ "$COUNT" -ne 1 ]; then
  echo "配信元 project-index の config の書き換え: failed"
  echo "grep -cxF '$OLD_LINE' $SETTINGS: $COUNT 件"
  exit 1
fi
awk -v old="$OLD_LINE" -v new="$NEW_LINE" '$0 == old { print new; next } { print }' "$SETTINGS" > "$NEW"
diff -u --label "$SETTINGS" --label "$SETTINGS" "$SETTINGS" "$NEW" || true
if [ "${1:-}" = "--dry-run" ]; then
  echo "配信元 project-index の config の書き換え: changed"
  exit 0
fi

# 適用（検証 → 退避 → 置き換え）
if ! grep -qxF "$NEW_LINE" "$NEW" || grep -qxF "$OLD_LINE" "$NEW"; then
  echo "検証: failed"
  exit 1
fi
if ! python3 -c "import sys, yaml; yaml.safe_load(open(sys.argv[1], encoding='utf-8'))" "$NEW"; then
  echo "検証: failed"
  exit 1
fi
echo "検証: ok"
cp -p "$SETTINGS" "$SETTINGS.bak-pr19"
cat "$NEW" > "$SETTINGS"
echo "配信元 project-index の config の書き換え: changed"

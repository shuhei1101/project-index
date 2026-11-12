#!/bin/sh
set -eu

SETTINGS=/home/shuhei2441/.config/dev-docs/settings.yaml
NEW_LINE='    config: /mnt/c/Users/shuhe/repo/project-index/.claude/worktrees/develop/project-index.yaml'
NEW_CONFIG=/mnt/c/Users/shuhe/repo/project-index/.claude/worktrees/develop/project-index.yaml

if grep -qxF "$NEW_LINE" "$SETTINGS"; then
  echo "配信元 project-index の config: ok"
else
  echo "配信元 project-index の config: failed"
  grep -n -A1 "id: project-index" "$SETTINGS" || true
  exit 1
fi
if [ -f "$NEW_CONFIG" ]; then
  echo "config が指すファイル: ok"
else
  echo "config が指すファイル: failed"
  echo "test -f $NEW_CONFIG"
  exit 1
fi

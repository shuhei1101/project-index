#!/bin/sh
set -eu

SETTINGS=/home/shuhei2441/.config/dev-docs/settings.yaml
WORKTREE=/mnt/c/Users/shuhe/repo/project-index/.claude/worktrees/develop

if [ -r "$SETTINGS" ]; then
  echo "端末の設定: ok"
else
  echo "端末の設定: failed"
  echo "test -r $SETTINGS"
  exit 1
fi
if [ -d "$WORKTREE" ]; then
  echo "develop の worktree: ok"
else
  echo "develop の worktree: failed"
  echo "test -d $WORKTREE"
  exit 1
fi

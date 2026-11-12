#!/bin/sh
set -eu

SETTINGS=/home/shuhei2441/.config/dev-docs/settings.yaml
if [ ! -f "$SETTINGS.bak-pr19" ]; then
  echo "退避したファイル: failed"
  echo "test -f $SETTINGS.bak-pr19"
  exit 1
fi
cp -p "$SETTINGS.bak-pr19" "$SETTINGS"
echo "端末の設定の書き戻し: changed"

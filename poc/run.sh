#!/bin/bash
# 使い方: run.sh {名前} [環境変数=値 ...]
# 端末の設定の複製・空の状態フォルダで起動し、約 5 秒後から 14 件の配信元の文書の一覧を 2 回ずつ API で取る
set -u
NAME=$1; shift
HERE=$(cd "$(dirname "$0")" && pwd); CLONE=$(dirname "$HERE")
D=/tmp/poc171; R=$D/runs/$NAME
rm -rf "$R"; mkdir -p "$R/state" "$R/prof" "$R/body"
SOURCES="dev-docs claude-balancer aituber knowledge mdmark ai-monitor voice-input gui-support mindstella observability project-index alias-inject rule-inject shuhdev-gateway"
cat /proc/loadavg > "$R/loadavg-before"
T0=$(date +%s.%N); echo "$T0" > "$R/t0"
env "$@" POC_NO_CHECKS=1 POC_NO_EXPORT=1 POC_TIMING_LOG="$R/timing.jsonl" POC_PROFILE_DIR="$R/prof" POC_PROFILE_SOURCES=${POC_PROFILE_SOURCES:-} \
  PROJECT_INDEX_CONFIG=$D/pi-settings.yaml PROJECT_INDEX_PORT=18786 PROJECT_INDEX_STATE_DIR="$R/state" \
  "$CLONE/.venv/bin/project-index" serve > "$R/pi.log" 2>&1 &
PI=$!
until ss -ltn | grep -q "127.0.0.1:18786 "; do sleep 0.1; done
sleep "$(python3 -c "import time;print(max(0,$T0+5-time.time()))")"
for s in $SOURCES; do
  for n in 1 2; do
    curl -s -o "$R/body/$s-$n.json" -w "$s $n %{http_code} %{time_total} $(date +%s.%N)\n" \
      "http://127.0.0.1:18786/sources/$s/docs?values=true&common_keys=true" >> "$R/api.txt"
  done
done
cat /proc/loadavg > "$R/loadavg-after"
kill $PI; wait $PI 2>/dev/null
echo done "$R"

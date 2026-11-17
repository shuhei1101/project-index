#!/bin/bash
# 使い方: run.sh {名前} {project-index のクローン} [環境変数=値 ...]
set -u
NAME=$1; CLONE=$2; shift 2
D=/tmp/poc147; R=$D/runs/$NAME
rm -rf "$R"; mkdir -p "$R/state" "$R/shots"
T0=$(date +%s.%N); echo "$T0" > "$R/t0"
env "$@" POC_T0="$T0" POC_TIMING_LOG="$R/timing.jsonl" PROJECT_INDEX_CONFIG=$D/pi-settings.yaml PROJECT_INDEX_PORT=18786 PROJECT_INDEX_STATE_DIR="$R/state" \
  uv run --directory "$CLONE" project-index serve > "$R/pi.log" 2>&1 &
PI=$!
DEV_DOCS_CONFIG=$D/dd-settings.yaml DEV_DOCS_PORT=18781 uv run --directory $D/dev-docs dev-docs serve > "$R/dd.log" 2>&1 &
DD=$!
python3 $D/sampler.py "$R/live.jsonl" "$(ss -ltnp | grep '127.0.0.1:8786 ' | grep -o 'pid=[0-9]*' | cut -d= -f2),$(ss -ltnp | grep '127.0.0.1:8781 ' | grep -o 'pid=[0-9]*' | cut -d= -f2)" &
SP=$!
# 起動からおよそ 5 秒後に最初の画面を開く（#145 の計測に合わせる）
until curl -s -o /dev/null http://127.0.0.1:18781/; do sleep 0.2; done
sleep $(python3 -c "import time;print(max(0,$T0+5-time.time()))")
SHOTS="$R/shots" node $D/dd2.cjs > "$R/dd2.out" 2>&1
# 裏の書き出しが終わるまで待つ（上限 180 秒）
for i in $(seq 1 180); do grep -q '"export_end"\|"export_skipped"' "$R/timing.jsonl" 2>/dev/null && break; sleep 1; done
sleep 2
kill $SP; pkill -P $PI; kill $PI; pkill -P $DD; kill $DD
wait 2>/dev/null
echo done "$R"

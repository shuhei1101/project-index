#!/usr/bin/env bash
# PoC のサーバーを py-spy の下で起動し、負荷を送って記録を集める。
# 使い方: run.sh {記録の名前} {負荷の秒数} [load.py の追加の引数...]
set -euo pipefail
NAME=$1; DURATION=$2; shift 2
HERE=$(cd "$(dirname "$0")" && pwd); WT=$(cd "$HERE/../.." && pwd)
ROOT=${PI_POC_ROOT:-/tmp/pi-poc}; PORT=${PI_POC_PORT:-8796}
OUT="$ROOT/out/$NAME"; mkdir -p "$OUT"
rm -rf "$ROOT/state"; mkdir -p "$ROOT/state"
# 前の起動の書き込みを commit の状態へ戻す
cut -d" " -f2 "$ROOT/worktrees.txt" | while read -r wt; do git -C "$wt" checkout -q HEAD -- . ; done
export PROJECT_INDEX_CONFIG="$ROOT/settings.yaml" PROJECT_INDEX_PORT=$PORT PROJECT_INDEX_STATE_DIR="$ROOT/state"
export PI_POC_STACKS="$OUT/stacks.txt"
py-spy record --threads --gil --idle --format raw -o "$OUT/pyspy.txt" -- "$WT/.venv/bin/python" -m project_index serve > "$OUT/serve.out" 2>&1 &
SPY=$!
until curl -s -o /dev/null "http://127.0.0.1:$PORT/sources"; do sleep 1; done
PID=$(pgrep -f -P "$SPY" "project_index serve" | head -1)
echo "server pid=$PID"
"$WT/.venv/bin/python" "$HERE/load.py" --port "$PORT" --server-pid "$PID" --out "$OUT/load.jsonl" --duration "$DURATION" "$@" || true
kill -INT "$PID" || true
wait "$SPY" || true
cp "$ROOT/state/logs/project-index.log"* "$OUT/" 2>/dev/null || true
echo "done: $OUT"

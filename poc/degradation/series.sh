#!/usr/bin/env bash
# PoC（#237）: 手順 1 のやり直しと、手順 2 の変種を同じ負荷で順に動かす。
# 使い方: series.sh {基準の秒数} {変種の秒数}
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
BASE=$1; EACH=$2
"$HERE/run.sh" step1b-baseline "$BASE"
PI_POC_WORKTREE_KEEP=200 "$HERE/run.sh" v-keep200 "$EACH"
PI_POC_DROP_EVICTED=1 "$HERE/run.sh" v-drop-evicted "$EACH"
PI_POC_CLIENT_TIMEOUT=600 "$HERE/run.sh" v-no-abandon "$EACH"
PI_POC_NO_SHIELD=1 "$HERE/run.sh" v-no-shield "$EACH"
PI_POC_GATE_NO_SLEEP=1 "$HERE/run.sh" v-gate-no-sleep "$EACH"
PI_POC_NO_GC=1 "$HERE/run.sh" v-no-gc "$EACH"
PI_POC_ADMIN_EXECUTOR=1 "$HERE/run.sh" v-admin-executor "$EACH"
echo series-done

#!/bin/bash
set -u

# 値はコレクターの 2 段の batch（200ms と 5s）を経て届くため、1 秒ごとに上限 10 秒まで取り直す
Q='test_session_duration_seconds{repository="project-index"}'
INTERVAL=1
LIMIT=10
elapsed=0
while :; do
  res=$(curl -sS -m 5 -G 'http://127.0.0.1:9090/api/v1/query' --data-urlencode "query=$Q" 2>&1)
  code=$?
  if [ $code -eq 0 ] && echo "$res" | grep -q '"result":\[{'; then
    echo "$res"
    echo "Prometheus の系列: ok"
    exit 0
  fi
  if [ $elapsed -ge $LIMIT ]; then
    echo "Prometheus の系列: failed"
    echo "curl -sS -m 5 -G http://127.0.0.1:9090/api/v1/query --data-urlencode query=$Q"
    echo "$res"
    exit 1
  fi
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
done

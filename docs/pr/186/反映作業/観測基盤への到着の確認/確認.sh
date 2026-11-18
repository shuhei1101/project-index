#!/bin/bash
set -u

Q='test_session_duration_seconds{repository="project-index"}'
if ! res=$(curl -sS -m 10 -G 'http://127.0.0.1:9090/api/v1/query' --data-urlencode "query=$Q" 2>&1); then
  echo "Prometheus の系列: failed"
  echo "curl -sS -m 10 -G http://127.0.0.1:9090/api/v1/query --data-urlencode query=$Q"
  echo "$res"
  exit 1
fi
echo "$res"
if echo "$res" | grep -q '"result":\[{'; then
  echo "Prometheus の系列: ok"
else
  echo "Prometheus の系列: failed"
  exit 1
fi

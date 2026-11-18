#!/bin/bash
set -u

OBS="$HOME/repo/observability"
rc=0

if grep -q '^observability_test_runs = ' "$OBS/pyproject.toml" 2>/dev/null; then
  echo "observability のクローンの pytest のプラグイン: ok"
else
  echo "observability のクローンの pytest のプラグイン: failed"
  echo "grep '^observability_test_runs = ' $OBS/pyproject.toml"
  rc=1
fi

if (exec 3<>/dev/tcp/127.0.0.1/14317) 2>/dev/null; then
  echo "収集のコレクター 127.0.0.1:14317: ok"
else
  echo "収集のコレクター 127.0.0.1:14317: failed"
  echo "exec 3<>/dev/tcp/127.0.0.1/14317"
  rc=1
fi

if err=$(curl -sS -m 5 -o /dev/null 'http://127.0.0.1:9090/-/ready' 2>&1); then
  echo "Prometheus 127.0.0.1:9090: ok"
else
  echo "Prometheus 127.0.0.1:9090: failed"
  echo "curl -sS -m 5 http://127.0.0.1:9090/-/ready"
  echo "$err"
  rc=1
fi

exit $rc

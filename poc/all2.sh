#!/bin/bash
# 延長した PoC: 同じ時間帯の構成 0 と、構成 4・3b・3b + 4・5・6・全部入りを 3 回ずつ流す
HERE=$(cd "$(dirname "$0")" && pwd)
for i in 1 2 3; do
  "$HERE/run.sh" x0-$i
  "$HERE/run.sh" x4-$i POC_GATE_ROWS=1 POC_CATFILE=1
  "$HERE/run.sh" x3b-$i POC_YAML_C3B=1
  "$HERE/run.sh" x3b4-$i POC_YAML_C3B=1 POC_GATE_ROWS=1 POC_CATFILE=1
  "$HERE/run.sh" x5-$i POC_COLLECT_CACHE=1
  "$HERE/run.sh" x6-$i POC_SCHEMA_CACHE=1
  "$HERE/run.sh" xall-$i POC_YAML_C3B=1 POC_GATE_ROWS=1 POC_CATFILE=1 POC_SCHEMA_CACHE=1 POC_COLLECT_CACHE=1
done
touch /tmp/poc171/all2.done

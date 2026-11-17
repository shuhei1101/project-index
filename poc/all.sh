#!/bin/bash
# 構成ごとに 3 回ずつ流す（構成 0・1a・1b・2・3）と、ai-monitor の cProfile の 1 回
HERE=$(cd "$(dirname "$0")" && pwd)
for i in 2 3; do "$HERE/run.sh" c0-$i; done
for i in 1 2 3; do "$HERE/run.sh" c1a-$i POC_PAUSE_ROWS=1; done
for i in 1 2 3; do "$HERE/run.sh" c1b-$i POC_LOAD_WORKERS=2; done
for i in 2 3; do "$HERE/run.sh" c2-$i POC_CATFILE=1; done
for i in 1 2 3; do "$HERE/run.sh" c12a-$i POC_PAUSE_ROWS=1 POC_CATFILE=1; done
for i in 1 2 3; do "$HERE/run.sh" c12b-$i POC_LOAD_WORKERS=2 POC_CATFILE=1; done
for i in 1 2 3; do "$HERE/run.sh" c3-$i POC_YAML_C=1; done
POC_PROFILE_SOURCES=ai-monitor "$HERE/run.sh" prof0
POC_PROFILE_SOURCES=ai-monitor "$HERE/run.sh" prof3 POC_YAML_C=1
touch /tmp/poc171/all.done

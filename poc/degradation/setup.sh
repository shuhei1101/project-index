#!/usr/bin/env bash
# 本番の端末の設定の配信元を /tmp/pi-poc へ複製し、PoC のサーバー用の端末の設定と worktree を作る。
# 本番のクローン・worktree には書き込まない（git clone --local で読むだけ）。
set -euo pipefail
SRC=/home/shuhei2441/repo
ROOT=${PI_POC_ROOT:-/tmp/pi-poc}
# 複製する配信元のリポジトリと、develop の他に作る worktree の数（本番の worktree の数の比で、合計 84 個にする）
declare -A EXTRA=(
  [ai-monitor]=29 [aituber]=8 [mdmark]=5 [project-index]=5 [mindstella]=4 [claude-balancer]=4
  [shuhdev-gateway]=3 [gui-support]=3 [alias-inject]=1 [dev-docs]=1 [knowledge]=1 [observability]=1
  [rule-inject]=2 [voice-paste]=3
)
mkdir -p "$ROOT/repo" "$ROOT/state" "$ROOT/out"
: > "$ROOT/worktrees.txt"
for r in "${!EXTRA[@]}"; do
  dst="$ROOT/repo/$r"
  if [ ! -d "$dst/.git" ]; then
    git clone -q --local --no-checkout "$SRC/$r" "$dst"
    git -C "$dst" config user.name pi-poc
    git -C "$dst" config user.email pi-poc@localhost
    git -C "$dst" worktree add -q -B develop "$dst/.claude/worktrees/develop" origin/develop
  fi
  echo "$r $dst/.claude/worktrees/develop" >> "$ROOT/worktrees.txt"
  for i in $(seq -w 1 "${EXTRA[$r]}"); do
    wt="$dst/.claude/worktrees/poc-wt-$i"
    [ -d "$wt" ] || git -C "$dst" worktree add -q -B "poc/wt-$i" "$wt" origin/develop
    echo "$r $wt" >> "$ROOT/worktrees.txt"
  done
done
# 端末の設定の複製（配信元のパスだけを複製へ向ける）
sed -e "s#$SRC/#$ROOT/repo/#g" "$HOME/.config/project-index/settings.yaml" > "$ROOT/settings.yaml"
echo "worktrees: $(wc -l < "$ROOT/worktrees.txt")"

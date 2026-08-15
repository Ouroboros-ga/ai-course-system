#!/usr/bin/env bash
# SmartCarb release 保留策略：仅保留最近 N 个，删除更旧的（永不删除 current 指向）
# 用法: bash smartcarb-prune-releases.sh [keep=5]
set -euo pipefail

KEEP="${1:-5}"
RELEASES_DIR=/opt/smartcarb/releases
CURRENT_DIR="$(readlink -f /opt/smartcarb/current 2>/dev/null || true)"

mapfile -t ALL < <(ls -1t "$RELEASES_DIR")
COUNT="${#ALL[@]}"
if [ "$COUNT" -le "$KEEP" ]; then
  echo "无需清理: 共 $COUNT 个 release（保留 $KEEP）"
  exit 0
fi

i=0
for name in "${ALL[@]}"; do
  i=$((i + 1))
  [ "$i" -le "$KEEP" ] && continue
  full="$RELEASES_DIR/$name"
  if [ -n "$CURRENT_DIR" ] && [ "$full" = "$CURRENT_DIR" ]; then
    echo "跳过 current 指向的 release: $name"
    continue
  fi
  echo "删除旧 release: $name"
  rm -rf "$full"
done
echo "剩余 $(ls -1 "$RELEASES_DIR" | wc -l) 个 release"

#!/usr/bin/env bash
# F3 实验受限网络创建/回退（部署变更脚本，本批交付、不执行）。
#
# 目标：专用实验 docker 网络，保留公开依赖下载，阻断宿主业务网、
# 169.254.169.254（metadata）与其他任务互访；不改动现有业务网络。
# 实际创建与容器切换另行确认维护窗口；未生效前服务如实标记未隔离。
#
# 用法：
#   bash scripts/create-isolated-network.sh plan      # 只打印将执行的命令（默认）
#   bash scripts/create-isolated-network.sh apply     # 创建网络＋写入规则
#   bash scripts/create-isolated-network.sh teardown  # 回退：删规则＋删网络
#
# 环境变量：
#   ISOLATED_NETWORK（默认 nexus-exp-restricted）
#   BLOCK_CIDRS（空格分隔，默认 "169.254.169.254/32 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16"）
#   PUBLIC_ALLOW_TCP（放行出网端口，默认 "80 443 53"；DNS 另见说明）
# 回退见 NETWORK_ISOLATION.md。
set -uo pipefail

NETWORK="${ISOLATED_NETWORK:-nexus-exp-restricted}"
# shellcheck disable=SC2206
BLOCK_CIDRS=(${BLOCK_CIDRS:-169.254.169.254/32 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16})
MODE="${1:-plan}"

bridge_if() { docker network inspect -f '{{.Options.com.docker.network.bridge.name}}' "$NETWORK" 2>/dev/null || echo "br-${NETWORK:0:10}"; }

if [ "$MODE" = "plan" ]; then
  echo "plan: docker network create --driver bridge $NETWORK"
  for cidr in "${BLOCK_CIDRS[@]}"; do
    echo "plan: iptables -I DOCKER-USER -o <bridge-if> -d $cidr -j DROP (反向一并处理见文档)"
  done
  echo "plan: 容器侧 --network=$NETWORK（经 REPRO_NETWORK_MAP 生效，不改业务网络）"
  exit 0
fi

if [ "$MODE" = "apply" ]; then
  if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
    docker network create --driver bridge --opt com.docker.network.bridge.enable_icc=true "$NETWORK"
  else
    echo "network exists: $NETWORK"
  fi
  BRIF="$(bridge_if)"
  for cidr in "${BLOCK_CIDRS[@]}"; do
    # 出向阻断（容器→目标）与返向保护（conntrack ESTABLISHED 放行由 DOCKER-USER 默认前置规则承担）。
    iptables -C DOCKER-USER -o "$BRIF" -d "$cidr" -j DROP 2>/dev/null \
      || iptables -I DOCKER-USER -o "$BRIF" -d "$cidr" -j DROP
  done
  echo "applied: $NETWORK (bridge $BRIF)"
  exit 0
fi

if [ "$MODE" = "teardown" ]; then
  BRIF="$(bridge_if)"
  for cidr in "${BLOCK_CIDRS[@]}"; do
    iptables -D DOCKER-USER -o "$BRIF" -d "$cidr" -j DROP 2>/dev/null || true
  done
  if docker network inspect "$NETWORK" >/dev/null 2>&1; then
    if [ -n "$(docker network inspect -f '{{len .Containers}}' "$NETWORK" 2>/dev/null)" ] \
       && [ "$(docker network inspect -f '{{len .Containers}}' "$NETWORK")" != "0" ]; then
      echo "refuse: network $NETWORK 仍有容器，先迁走再回退（见文档）" >&2
      exit 1
    fi
    docker network rm "$NETWORK"
  fi
  echo "teardown done: $NETWORK"
  exit 0
fi

echo "未知模式：$MODE（plan/apply/teardown）" >&2
exit 2

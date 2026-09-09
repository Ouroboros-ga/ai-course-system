#!/usr/bin/env bash
# T1 宿主侧隔离核验（B13）：对任务容器做 docker inspect 断言。
#
# 为什么在宿主：任务镜像内没有 docker CLI（回执 T1-b 已记录），容器内无法
# 自证 Memory/PidsLimit/Privileged/Mounts/NetworkMode 是否真的生效。
# 本脚本把回执里"人工核验"的结论固化为可复现断言。
#
# 用法（在部署宿主上，容器处于运行态时执行）：
#   bash scripts/verify_host.sh <container_name>
# 可选环境变量（缺省按已确认 scope 的默认资源）：
#   EXPECT_MEMORY_BYTES（默认 2147483648 = 2g）
#   EXPECT_PIDS（默认 512）
#   EXPECT_NETWORK（默认 bridge；受限网络部署后传实际网络名）
#   EXPECT_ISOLATED（默认 0；为 1 时额外断言 metadata 不可达，见下）
#
# 退出码：0=全部通过；1=有断言失败（逐条打印 OK/FAIL）。
set -uo pipefail

CONTAINER="${1:?用法: verify_host.sh <container_name>}"
EXPECT_MEMORY_BYTES="${EXPECT_MEMORY_BYTES:-2147483648}"
EXPECT_PIDS="${EXPECT_PIDS:-512}"
EXPECT_NETWORK="${EXPECT_NETWORK:-bridge}"

inspect() { docker inspect --format "$1" "$CONTAINER" 2>/dev/null; }

fail=0
check() {
  local label="$1" actual="$2" expected="$3"
  if [ "$actual" = "$expected" ]; then
    echo "OK   ${label}=${actual}"
  else
    echo "FAIL ${label}=${actual}（期望 ${expected}）"
    fail=1
  fi
}

check "Memory"      "$(inspect '{{.HostConfig.Memory}}')"      "$EXPECT_MEMORY_BYTES"
check "PidsLimit"   "$(inspect '{{.HostConfig.PidsLimit}}')"   "$EXPECT_PIDS"
check "Privileged"  "$(inspect '{{.HostConfig.Privileged}}')"  "false"
check "NetworkMode" "$(inspect '{{.HostConfig.NetworkMode}}')" "$EXPECT_NETWORK"
check "Mounts"      "$(inspect '{{len .Mounts}}')"             "0"
check "DockerSock"  "$(inspect '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' | grep -c 'docker.sock' || true)" "0"

# F3：受限网络生效断言（EXPECT_ISOLATED=1 时）：metadata 169.254.169.254
# 必须不可达（容器内 5s 超时即算阻断通过；可达即 FAIL）。
if [ "${EXPECT_ISOLATED:-0}" = "1" ]; then
  if docker exec "$CONTAINER" timeout 5 curl -fsS -o /dev/null http://169.254.169.254/ 2>/dev/null; then
    echo "FAIL Metadata=reachable（期望不可达）"
    fail=1
  else
    echo "OK   Metadata=blocked"
  fi
fi

echo "---"
if [ "$fail" -eq 0 ]; then
  echo "宿主隔离断言全部通过：${CONTAINER}"
else
  echo "宿主隔离断言存在失败：${CONTAINER}"
fi
exit "$fail"

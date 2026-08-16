#!/usr/bin/env bash
# SmartCarb 标准发布脚本（服务器端）
#
# 用法: bash /opt/smartcarb/scripts/smartcarb-release.sh [ref=dev-liu] [keep=5]
#
# 流程:
#   1. 解析远端分支 HEAD，以短 hash 建 release 目录
#   2. 前端构建：dist 纳入发布产物（复用 shared/node_modules/frontend 依赖缓存）
#   3. 原子切换 current 软链
#   4. 重启后端并做健康检查（openapi + 首页）
#   5. 调用 smartcarb-prune-releases.sh 清理旧 release
#
# 前置条件: /opt/smartcarb/shared/（env/venvs/node_modules/media）已就绪
set -euo pipefail

REPO_URL="https://gitee.com/ljlouroboros/ai-course-system.git"
DEPLOY_ROOT=/opt/smartcarb
RELEASES_DIR="$DEPLOY_ROOT/releases"
SHARED_DIR="$DEPLOY_ROOT/shared"
NODE_HOME=/opt/node-v22-current
BRANCH="${1:-dev-liu}"
KEEP="${2:-5}"

# 1. 解析目标提交
echo "==> 解析远端分支 $BRANCH"
SHA="$(git ls-remote "$REPO_URL" "refs/heads/$BRANCH" | awk '{print $1}')"
if [ -z "$SHA" ]; then
  echo "错误: 无法解析远端分支 $BRANCH（检查网络/仓库地址）" >&2
  exit 1
fi
SHORT="${SHA:0:8}"
RELEASE_DIR="$RELEASES_DIR/$SHORT"
echo "目标提交: $SHA ($SHORT)"

if [ ! -d "$RELEASE_DIR" ]; then
  echo "==> 克隆 release $SHORT"
  git clone --quiet --single-branch --branch "$BRANCH" "$REPO_URL" "$RELEASE_DIR"
fi
cd "$RELEASE_DIR"

# 2. 前端构建（dist 不纳入 git，必须在发布时构建）
# 注意：node_modules 复用共享 pnpm 缓存时不能直接 `pnpm build`（pnpm 预检
# 会因符号链接触发重装并因无 TTY 中止），这里直接调用 vite 入口绕过预检。
if [ ! -f frontend/dist/index.html ]; then
  echo "==> 构建前端 dist（复用共享依赖缓存）"
  rm -f frontend/node_modules
  ln -sfn "$SHARED_DIR/node_modules/frontend" frontend/node_modules
  (cd frontend && export PATH="$NODE_HOME/bin:$PATH" && node node_modules/vite/bin/vite.js build)
  [ -f frontend/dist/index.html ] || { echo "前端构建失败: 无 dist/index.html" >&2; exit 1; }
else
  echo "==> release 已含 dist，跳过构建"
fi

# 3. 原子切换 current
echo "==> 切换 current -> $RELEASE_DIR"
ln -sfn "$RELEASE_DIR" "$DEPLOY_ROOT/current.new"
mv -Tf "$DEPLOY_ROOT/current.new" "$DEPLOY_ROOT/current"

# 4. 重启后端并健康检查
echo "==> 重启后端"
systemctl restart smartcarb-backend
# 后端启动含 2 workers + 重导入，固定 sleep 不足会触发假健康检查失败；
# 改为轮询重试（默认最多 30 次 × 2 秒，可用环境变量覆盖）。
HEALTH_RETRIES="${HEALTH_RETRIES:-30}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-2}"
backend_ready=0
for i in $(seq 1 "$HEALTH_RETRIES"); do
  if curl -fsS -o /dev/null http://127.0.0.1:8000/openapi.json 2>/dev/null; then
    backend_ready=1
    echo "==> 后端就绪（第 ${i} 次探测）"
    break
  fi
  sleep "$HEALTH_INTERVAL"
done
if [ "$backend_ready" -ne 1 ]; then
  echo "后端健康检查失败（${HEALTH_RETRIES} 次探测均未就绪）；注意 current 已切换、服务已重启，请人工排查" >&2
  exit 1
fi
curl -fsS -o /dev/null http://127.0.0.1/ \
  || { echo "前端首页检查失败" >&2; exit 1; }
echo "==> 发布完成: $RELEASE_DIR"

# 5. 清理旧 release
bash "$DEPLOY_ROOT/scripts/smartcarb-prune-releases.sh" "$KEEP"

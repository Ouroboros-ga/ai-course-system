#!/usr/bin/env bash
# dev-stack.sh - 统一启动 PaddleOCR 容器 + 主后端（Linux/macOS 开发）。
# 统一课程建设九步实施计划 Step 2：OCR 服务随主后端同步启动/关闭。
#
# 流程：检查 Docker -> 启 paddleocr 容器 -> 轮询 /health -> 启动后端 uvicorn
#       -> 捕获 Ctrl+C/后端退出 -> 停止本地 OCR 容器。
#
# 用法：
#   ./scripts/dev-stack.sh                  # 启动 OCR + 后端
#   ./scripts/dev-stack.sh --skip-backend   # 仅启动 OCR 容器
#   ./scripts/dev-stack.sh --skip-ocr       # 跳过 OCR
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OCR_COMPOSE="$REPO_ROOT/deploy/paddleocr/compose.yml"
BACKEND_DIR="$REPO_ROOT/backend"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
HEALTH_TIMEOUT_S="${HEALTH_TIMEOUT_S:-120}"
SKIP_BACKEND=0
SKIP_OCR=0

for arg in "$@"; do
  case "$arg" in
    --skip-backend) SKIP_BACKEND=1 ;;
    --skip-ocr)     SKIP_OCR=1 ;;
    *) echo "[dev-stack] unknown arg: $arg" >&2 ;;
  esac
done

log()  { printf '\033[36m[dev-stack]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[dev-stack]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[dev-stack]\033[0m %s\n' "$*"; }

# 1. 检查 Docker
if [ "$SKIP_OCR" -eq 0 ]; then
  log "Checking Docker..."
  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker 不可用。OCR 服务不会启动；OCR 相关任务会以 OCR_SERVICE_UNAVAILABLE 失败。"
    SKIP_OCR=1
  else
    ok "Docker: $(docker --version)"
  fi
fi

# 2. 启动 PaddleOCR 容器
if [ "$SKIP_OCR" -eq 0 ]; then
  log "Starting PaddleOCR container ($OCR_COMPOSE)..."
  if ! docker compose -f "$OCR_COMPOSE" up -d --build; then
    warn "OCR 容器启动失败。继续仅启动后端（OCR 端口 fail-closed）。"
    SKIP_OCR=1
  else
    ok "OCR 容器已启动 (127.0.0.1:8090)"
  fi
fi

# 3. 轮询 /health
if [ "$SKIP_OCR" -eq 0 ]; then
  log "Waiting for OCR /health (最多 ${HEALTH_TIMEOUT_S}s)..."
  deadline=$(( $(date +%s) + HEALTH_TIMEOUT_S ))
  healthy=0
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if curl -sf --max-time 4 http://127.0.0.1:8090/health >/dev/null 2>&1; then
      body="$(curl -sf --max-time 4 http://127.0.0.1:8090/health 2>/dev/null || echo '{}')"
      status="$(printf '%s' "$body" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("status",""))' 2>/dev/null || echo '')"
      if [ "$status" = "ok" ]; then
        healthy=1
        ok "OCR healthy: $body"
        break
      fi
    fi
    sleep 2
  done
  if [ "$healthy" -ne 1 ]; then
    warn "OCR /health 未就绪（超时）。后端仍会启动；OCR 端口会 fail-closed 直到服务就绪。"
  fi
fi

# 5. 退出时停止 OCR 容器（trap 确保后端退出/中断都会清理）
cleanup() {
  if [ "$SKIP_OCR" -eq 0 ]; then
    log "Stopping local OCR container..."
    docker compose -f "$OCR_COMPOSE" down >/dev/null 2>&1 || true
    ok "OCR container stopped."
  fi
  ok "dev-stack done."
}
trap cleanup EXIT INT TERM

# 4. 启动后端
if [ "$SKIP_BACKEND" -eq 0 ]; then
  log "Starting backend uvicorn ($BACKEND_HOST:$BACKEND_PORT)..."
  cd "$BACKEND_DIR"
  export PADDLEOCR_URL="${PADDLEOCR_URL:-http://127.0.0.1:8090}"
  python -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload
fi

# trap 会执行 cleanup

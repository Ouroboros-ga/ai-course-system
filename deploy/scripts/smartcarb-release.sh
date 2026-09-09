#!/usr/bin/env bash
# SmartCarb 标准发布脚本（服务器端）
#
# 用法: bash /opt/smartcarb/scripts/smartcarb-release.sh [ref=dev-liu|commit-sha] [keep=5]
#
# 流程:
#   1. 解析目标（分支 HEAD 或显式 commit SHA），以短 hash 建 release 目录并锁定 SHA
#   2. 前端构建：dist 纳入发布产物（复用 shared/node_modules/frontend 依赖缓存）
#   3. Alembic 迁移：release 目录内显式 upgrade head（唯一 head 校验；失败即中止）
#   4. 原子切换 current 软链
#   5. 重启后端并做健康检查（openapi + 首页）
#   6. Nexus 独立运行时同步：nexus/ → /opt/smartcarb/nexus-runtime（保留旧副本，
#      uv.lock 变化才 uv sync --frozen）并重启 nexus-runtime + 健康检查
#   7. 同步 repro-runtime 控制面（6c）＋重启语料常驻单元（6d）
#   8. 调用 smartcarb-prune-releases.sh 清理旧 release
#
# CR6 说明：切 current **不会**恢复/更新独立 Nexus Runtime（独立目录 + 独立 venv），
# 迁移也不再假设由他人执行——三步都在本脚本内显式完成。仅当本次发布确认无迁移、
# 无 Nexus 变更时才允许跳过（人工确认后设环境变量）:
#   SMARTCARB_SKIP_MIGRATIONS=1 / SMARTCARB_SKIP_NEXUS=1 / SMARTCARB_SKIP_PRUNE=1
# 验收期间建议 SMARTCARB_SKIP_PRUNE=1 保留旧 release 与旧索引直到回退窗口关闭。
#
# 前置条件: /opt/smartcarb/shared/（env/venvs/node_modules/media）已就绪
set -euo pipefail

REPO_URL="https://gitee.com/ljlouroboros/ai-course-system.git"
DEPLOY_ROOT=/opt/smartcarb
RELEASES_DIR="$DEPLOY_ROOT/releases"
SHARED_DIR="$DEPLOY_ROOT/shared"
ENV_DIR="$SHARED_DIR/env"
NODE_HOME=/opt/node-v22-current
BACKEND_VENV="${SMARTCARB_BACKEND_VENV:-$SHARED_DIR/venvs/backend-py312}"
BACKEND_PY="$BACKEND_VENV/bin/python"
NEXUS_DIR="$DEPLOY_ROOT/nexus-runtime"
REPRO_DIR="$DEPLOY_ROOT/repro-runtime"
REF="${1:-dev-liu}"
KEEP="${2:-5}"

_fail() { echo "错误: $*" >&2; exit 1; }

# 1. 解析目标提交：分支名 → 远端 HEAD；40/短 SHA → 锁定该提交（发布需批准 SHA）
BRANCH=""
SHA=""
if [[ "$REF" =~ ^[0-9a-f]{7,40}$ ]]; then
  SHA="$REF"
  echo "==> 按锁定提交发布: $SHA"
else
  BRANCH="$REF"
  echo "==> 解析远端分支 $BRANCH"
  SHA="$(git ls-remote "$REPO_URL" "refs/heads/$BRANCH" | awk '{print $1}')"
  if [ -z "$SHA" ]; then
    _fail "无法解析远端分支 $BRANCH（检查网络/仓库地址）"
  fi
fi
SHORT="${SHA:0:8}"
RELEASE_DIR="$RELEASES_DIR/$SHORT"
echo "目标提交: $SHA ($SHORT)"

if [ ! -d "$RELEASE_DIR" ]; then
  echo "==> 克隆 release $SHORT"
  if [ -n "$BRANCH" ]; then
    git clone --quiet --single-branch --branch "$BRANCH" "$REPO_URL" "$RELEASE_DIR"
  else
    git clone --quiet "$REPO_URL" "$RELEASE_DIR"
    git -C "$RELEASE_DIR" checkout --quiet "$SHA"
  fi
fi
ACTUAL_SHA="$(git -C "$RELEASE_DIR" rev-parse HEAD)"
[ "${ACTUAL_SHA:0:${#SHA}}" = "$SHA" ] \
  || _fail "release 目录实际提交 $ACTUAL_SHA 与请求 $SHA 不一致"
SHA="$ACTUAL_SHA"
cd "$RELEASE_DIR"

# 2. 前端构建（dist 不纳入 git，必须在发布时构建）
# 注意：node_modules 复用共享 pnpm 缓存时不能直接 `pnpm build`（pnpm 预检
# 会因符号链接触发重装并因无 TTY 中止），这里直接调用 vite 入口绕过预检。
if [ ! -f frontend/dist/index.html ]; then
  echo "==> 构建前端 dist（复用共享依赖缓存）"
  rm -f frontend/node_modules
  ln -sfn "$SHARED_DIR/node_modules/frontend/node_modules" frontend/node_modules
  (cd frontend && export PATH="$NODE_HOME/bin:$PATH" && node node_modules/vite/bin/vite.js build)
  [ -f frontend/dist/index.html ] || { echo "前端构建失败: 无 dist/index.html" >&2; exit 1; }
else
  echo "==> release 已含 dist，跳过构建"
fi

# 3. Alembic 迁移（在切换 current 之前执行；失败即中止，旧代码仍在服务）
ALEMBIC_BEFORE="(skipped)"
ALEMBIC_AFTER="(skipped)"
if [ "${SMARTCARB_SKIP_MIGRATIONS:-0}" != "1" ]; then
  [ -x "$BACKEND_PY" ] || _fail "后端 venv 不存在: $BACKEND_PY"
  echo "==> Alembic 迁移（upgrade head）"
  set -a
  for env_file in backend.env database.env postgres.env runtime-paths.env; do
    if [ -f "$ENV_DIR/$env_file" ]; then
      # 环境文件由人工维护，可能含非 shell 行（中文注释/说明）；加载失败不阻断发布。
      set +e
      . "$ENV_DIR/$env_file" 2>/dev/null
      set -e
    fi
  done
  set +a
  # 迁移账号优先：应用账号无 schema public CREATE 权限（PG15+ 默认），
  # 直接用应用 DSN 跑 alembic 会在 CREATE TABLE 处 permission denied。
  MIGRATION_DSN="$("$BACKEND_PY" - <<'PY' 2>/dev/null
import os
from urllib.parse import urlsplit, urlunsplit, quote
app = os.environ.get("AI_COURSE_DATABASE_URL", "")
user = os.environ.get("AI_COURSE_MIGRATION_DB_USER", "")
password = os.environ.get("AI_COURSE_MIGRATION_DB_PASSWORD", "")
if app and user and password:
    parts = urlsplit(app)
    netloc = f"{quote(user)}:{quote(password)}@{parts.hostname}:{parts.port or 5432}"
    print(urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment)))
PY
)"
  if [ -n "$MIGRATION_DSN" ]; then
    echo "==> 使用迁移账号执行 Alembic（AI_COURSE_MIGRATION_DB_*）"
    export AI_COURSE_DATABASE_URL="$MIGRATION_DSN"
  fi
  cd "$RELEASE_DIR/backend"
  HEAD_COUNT="$("$BACKEND_PY" -m alembic -c alembic.ini heads \
    | sed -n 's/.*(head).*/x/p' | wc -l)"
  [ "$HEAD_COUNT" -eq 1 ] \
    || _fail "alembic heads 数量为 $HEAD_COUNT（必须唯一 head，先修迁移链）"
  ALEMBIC_BEFORE="$("$BACKEND_PY" -m alembic -c alembic.ini current 2>/dev/null | tail -1)"
  "$BACKEND_PY" -m alembic -c alembic.ini upgrade head
  ALEMBIC_AFTER="$("$BACKEND_PY" -m alembic -c alembic.ini current 2>/dev/null | tail -1)"
  echo "==> 迁移完成: ${ALEMBIC_BEFORE:-<empty>} -> ${ALEMBIC_AFTER:-<empty>}"
  cd "$RELEASE_DIR"
else
  echo "==> 跳过 Alembic 迁移（SMARTCARB_SKIP_MIGRATIONS=1，需人工确认无迁移）"
fi

# 4. 原子切换 current
echo "==> 切换 current -> $RELEASE_DIR"
ln -sfn "$RELEASE_DIR" "$DEPLOY_ROOT/current.new"
mv -Tf "$DEPLOY_ROOT/current.new" "$DEPLOY_ROOT/current"

# 5. 重启后端并健康检查
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

# 6. Nexus 独立运行时同步（独立目录 + 独立 venv；切 current 不影响它）
NEXUS_PREVIOUS="(skipped)"
if [ "${SMARTCARB_SKIP_NEXUS:-0}" != "1" ]; then
  [ -d "$RELEASE_DIR/nexus" ] || _fail "release 缺少 nexus/ 目录"
  echo "==> 同步 Nexus Runtime -> $NEXUS_DIR"
  mkdir -p "$NEXUS_DIR" "$SHARED_DIR/backups"
  if [ -f "$NEXUS_DIR/RELEASE_INFO" ]; then
    NEXUS_PREVIOUS="$(sed -n 's/^commit=//p' "$NEXUS_DIR/RELEASE_INFO" | head -1)"
  fi
  if [ -n "$NEXUS_PREVIOUS" ] && [ "$NEXUS_PREVIOUS" != "$SHA" ]; then
    tar -czf "$SHARED_DIR/backups/nexus-runtime-${NEXUS_PREVIOUS:0:8}.tgz" \
      -C "$NEXUS_DIR" --exclude .venv --exclude '__pycache__' . \
      || _fail "Nexus 旧代码备份失败"
    echo "==> Nexus 旧代码备份: $SHARED_DIR/backups/nexus-runtime-${NEXUS_PREVIOUS:0:8}.tgz"
  fi
  LOCK_BEFORE="$(sha256sum "$NEXUS_DIR/uv.lock" 2>/dev/null | awk '{print $1}' || true)"
  rsync -a --delete --exclude '.venv' --exclude '__pycache__' \
    --exclude '.pytest_cache' "$RELEASE_DIR/nexus/" "$NEXUS_DIR/"
  LOCK_AFTER="$(sha256sum "$NEXUS_DIR/uv.lock" | awk '{print $1}')"
  if [ "$LOCK_BEFORE" != "$LOCK_AFTER" ]; then
    UV_BIN="$(command -v uv || echo /root/.local/bin/uv)"
    [ -x "$UV_BIN" ] || _fail "uv.lock 变化但 uv 不可用: $UV_BIN（先装 uv 再发布）"
    echo "==> Nexus 依赖变化，uv sync --frozen"
    (cd "$NEXUS_DIR" && "$UV_BIN" sync --frozen)
  else
    echo "==> Nexus 依赖未变化，跳过 uv sync"
  fi
  # 6b. Nexus 域显式迁移（任务书 T2／P2 §9.7：不写启动时 DDL）
  if [ "${SMARTCARB_SKIP_NEXUS_MIGRATIONS:-0}" != "1" ]; then
    echo "==> Nexus 域迁移（scripts/apply_nexus_migrations.py）"
    [ -x "$NEXUS_DIR/.venv/bin/python" ] \
      || _fail "Nexus venv 不存在：$NEXUS_DIR/.venv（先 uv sync）"
    set -a
    if [ -f "$ENV_DIR/nexus.env" ]; then
      set +e; . "$ENV_DIR/nexus.env" 2>/dev/null; set -e
    fi
    set +a
    if [ -z "${NEXUS_POSTGRES_DSN:-}" ]; then
      echo "==> 未配置 NEXUS_POSTGRES_DSN，跳过 Nexus 域迁移（内存/无 PG 部署）"
    else
      (cd "$NEXUS_DIR" && .venv/bin/python scripts/apply_nexus_migrations.py) \
        || _fail "Nexus 域迁移失败；已中止发布（nexus-runtime 未重启）"
    fi
  else
    echo "==> 跳过 Nexus 域迁移（SMARTCARB_SKIP_NEXUS_MIGRATIONS=1）"
  fi

  printf 'commit=%s\nbranch=%s\nreleased_at=%s\n' \
    "$SHA" "${BRANCH:-<locked>}" "$(date -Is)" > "$NEXUS_DIR/RELEASE_INFO"
  systemctl restart nexus-runtime
  nexus_ready=0
  for i in $(seq 1 "$HEALTH_RETRIES"); do
    if curl -fsS -o /dev/null http://127.0.0.1:8300/health 2>/dev/null; then
      nexus_ready=1
      echo "==> Nexus Runtime 就绪（第 ${i} 次探测）"
      break
    fi
    sleep "$HEALTH_INTERVAL"
  done
  if [ "$nexus_ready" -ne 1 ]; then
    echo "Nexus Runtime 健康检查失败；Backend 已切换并迁移（$ALEMBIC_BEFORE -> $ALEMBIC_AFTER）。" >&2
    echo "回退：用 $SHARED_DIR/backups/nexus-runtime-*.tgz 恢复 Nexus，或核对 $NEXUS_DIR/RELEASE_INFO" >&2
    exit 1
  fi
else
  echo "==> 跳过 Nexus Runtime 同步（SMARTCARB_SKIP_NEXUS=1，需人工确认无 Nexus 变更）"
fi

# 6c. 自主实验执行控制面同步（deploy/repro-runtime → $REPRO_DIR；独立 venv/数据）
if [ "${SMARTCARB_SKIP_REPRO_RUNTIME:-0}" != "1" ]; then
  if [ -d "$RELEASE_DIR/deploy/repro-runtime" ] \
      && systemctl cat repro-runtime >/dev/null 2>&1; then
    echo "==> 同步 repro-runtime 控制面 -> $REPRO_DIR"
    mkdir -p "$REPRO_DIR"
    rsync -a --delete --exclude '.venv' --exclude 'data' --exclude '.token' \
      --exclude '__pycache__' --exclude '.pytest_cache' \
      "$RELEASE_DIR/deploy/repro-runtime/" "$REPRO_DIR/"
    systemctl restart repro-runtime
    repro_ready=0
    for i in $(seq 1 "$HEALTH_RETRIES"); do
      if curl -fsS -o /dev/null http://127.0.0.1:8401/health 2>/dev/null; then
        repro_ready=1
        echo "==> repro-runtime 就绪（第 ${i} 次探测）"
        break
      fi
      sleep "$HEALTH_INTERVAL"
    done
    if [ "$repro_ready" -ne 1 ]; then
      echo "repro-runtime 健康检查失败；控制面代码已同步，请人工排查" >&2
      exit 1
    fi
  else
    echo "==> 跳过 repro-runtime 同步（无单元或无目录）"
  fi
else
  echo "==> 跳过 repro-runtime 同步（SMARTCARB_SKIP_REPRO_RUNTIME=1）"
fi

# 6d. 语料 RAG 常驻单元（随 current 切换重启，避免旧进程持旧代码）
if systemctl cat smartcarb-corpus-embedding >/dev/null 2>&1; then
  echo "==> 重启语料 embedding 服务（loopback 8310）"
  systemctl restart smartcarb-corpus-embedding
  corpus_ready=0
  for i in $(seq 1 "$HEALTH_RETRIES"); do
    if curl -fsS -o /dev/null http://127.0.0.1:8310/health 2>/dev/null; then
      corpus_ready=1
      echo "==> 语料 embedding 就绪（第 ${i} 次探测）"
      break
    fi
    sleep "$HEALTH_INTERVAL"
  done
  # 不阻断发布：backend 启动不依赖该服务，查询侧有降级；如实告警。
  [ "$corpus_ready" -eq 1 ] \
    || echo "语料 embedding 健康检查失败；请人工排查（发布已继续）" >&2
fi
if systemctl cat smartcarb-corpus-worker >/dev/null 2>&1; then
  systemctl restart smartcarb-corpus-worker || true
  echo "==> 语料构建 worker 已重启（空闲轮询；有 queued 构建时自动开工）"
fi

# 7. 记录本次发布（回退清单）并清理旧 release
cat > "$RELEASE_DIR/RELEASE_INFO" <<EOF
commit=$SHA
branch=${BRANCH:-<locked>}
alembic_before=$ALEMBIC_BEFORE
alembic_after=$ALEMBIC_AFTER
nexus_previous=$NEXUS_PREVIOUS
released_at=$(date -Is)
EOF
echo "==> 发布完成: $RELEASE_DIR"

if [ "${SMARTCARB_SKIP_PRUNE:-0}" != "1" ]; then
  bash "$DEPLOY_ROOT/scripts/smartcarb-prune-releases.sh" "$KEEP"
else
  echo "==> 跳过清理旧 release（SMARTCARB_SKIP_PRUNE=1，验收回退窗口内保留）"
fi

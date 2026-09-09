#!/usr/bin/env bash
# CR6 语料 RAG 上线只读预检（服务器端入口）
#
# 用法: bash /opt/smartcarb/scripts/corpus-preflight.sh [--json]
#
# 读取受信任部署 env（不打印任何 env 值），调用
# backend/scripts/corpus_preflight.py 输出 JSON 报告：
#   schema_head / source_manifest / model_ready / model_fingerprint /
#   dimension / FTS / active_release / resource_margin
# 只读：不写库、不建目录、不下载模型、不调用回答模型；退出码 2 表示有
# 阻断项（errors 非空），逐项修复后再执行发布。
#
# 覆盖点（默认值与 systemd 单元一致）：
#   SMARTCARB_APP_ROOT=/opt/smartcarb/current
#   SMARTCARB_BACKEND_VENV=/opt/smartcarb/shared/venvs/backend-py312
#   SMARTCARB_ENV_DIR=/opt/smartcarb/shared/env
set -euo pipefail

APP_ROOT="${SMARTCARB_APP_ROOT:-/opt/smartcarb/current}"
BACKEND_ROOT="${APP_ROOT}/backend"
VENV="${SMARTCARB_BACKEND_VENV:-/opt/smartcarb/shared/venvs/backend-py312}"
ENV_DIR="${SMARTCARB_ENV_DIR:-/opt/smartcarb/shared/env}"

if [ ! -x "${VENV}/bin/python" ]; then
  echo "错误: 后端 venv 不存在: ${VENV}/bin/python" >&2
  exit 2
fi
if [ ! -f "${BACKEND_ROOT}/scripts/corpus_preflight.py" ]; then
  echo "错误: 预检脚本不存在: ${BACKEND_ROOT}/scripts/corpus_preflight.py" >&2
  exit 2
fi

# 与 smartcarb-backend / corpus 单元同源的配置；缺文件即跳过（预检会如实报缺）
set -a
for env_file in backend.env database.env runtime-paths.env corpus-embedding.env; do
  if [ -f "${ENV_DIR}/${env_file}" ]; then
    # shellcheck disable=SC1090
    . "${ENV_DIR}/${env_file}"
  fi
done
set +a

export PYTHONPATH="${BACKEND_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
cd "${BACKEND_ROOT}"
exec "${VENV}/bin/python" "${BACKEND_ROOT}/scripts/corpus_preflight.py" "$@"

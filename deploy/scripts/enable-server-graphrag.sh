#!/usr/bin/env bash
set -euo pipefail

readonly app_root="/opt/smartcarb-git"
readonly backend_root="${app_root}/backend"
readonly backend_env="${backend_root}/.env"
readonly graph_python="${backend_root}/.venv-graphrag/bin/python"
readonly service_name="smartcarb-backend.service"

test -f "${backend_env}"
test -x "${graph_python}"
umask 077

set_env_value() {
  local target_file="$1"
  local key="$2"
  local value="$3"
  local temporary_file
  temporary_file="$(mktemp "${target_file}.tmp.XXXXXX")"
  awk -v key="${key}" -v value="${value}" '
    BEGIN { replaced = 0 }
    $0 ~ "^" key "=" {
      if (!replaced) {
        print key "=" value
        replaced = 1
      }
      next
    }
    { print }
    END {
      if (!replaced) print key "=" value
    }
  ' "${target_file}" > "${temporary_file}"
  chmod 600 "${temporary_file}"
  mv -f "${temporary_file}" "${target_file}"
}

cd "${backend_root}"
PYTHONPATH="${backend_root}" "${graph_python}" - <<'PY'
import graphrag
from app.platform.knowledge.graphrag_runner import GraphRagRunner

assert graphrag is not None
assert GraphRagRunner is not None
PY

"${backend_root}/.venv/bin/python" - <<'PY'
from pathlib import Path

from app.core.config import settings

assert all((
    settings.GRAPHRAG_COMPLETION_MODEL,
    settings.GRAPHRAG_COMPLETION_API_BASE,
    settings.GRAPHRAG_COMPLETION_API_KEY,
    settings.GRAPHRAG_EMBEDDING_MODEL,
)), "GraphRAG completion/embedding configuration is incomplete"
if settings.GRAPHRAG_EMBEDDING_PROVIDER.strip().lower() in {
    "local_bge", "bge-local", "local"
}:
    assert Path(settings.GRAPHRAG_EMBEDDING_LOCAL_PATH).exists(), (
        "GraphRAG local embedding path does not exist"
    )
else:
    assert settings.GRAPHRAG_EMBEDDING_API_BASE
    assert settings.GRAPHRAG_EMBEDDING_API_KEY
assert settings.GRAPHRAG_MAX_INPUT_TOKENS == 25000
assert 0 < settings.GRAPHRAG_MAX_ESTIMATED_COST_USD <= 0.70
PY

backup_env="${backend_env}.before-graphrag-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "${backend_env}" "${backup_env}"
chmod 600 "${backup_env}"
set_env_value "${backend_env}" GRAPHRAG_ENABLED true
chmod 600 "${backend_env}"

if ! systemctl restart "${service_name}"; then
  cp -p "${backup_env}" "${backend_env}"
  systemctl restart "${service_name}" || true
  echo "Backend restart failed; GraphRAG flag restored" >&2
  exit 1
fi

for _attempt in $(seq 1 30); do
  if curl -fsS --max-time 5 http://127.0.0.1:8000/ >/dev/null; then
    echo "GraphRAG runtime flag enabled; backend is healthy"
    exit 0
  fi
  sleep 2
done

cp -p "${backup_env}" "${backend_env}"
systemctl restart "${service_name}" || true
echo "Backend health check failed; GraphRAG flag restored" >&2
exit 1

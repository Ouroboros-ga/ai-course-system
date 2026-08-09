#!/usr/bin/env bash
set -euo pipefail

readonly app_root="/opt/smartcarb-git"
readonly backend_env="${app_root}/backend/.env"
readonly judge0_env="${app_root}/deploy/judge0/.env"

test -f "${backend_env}"
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

if [[ ! -f "${judge0_env}" ]]; then
  judge0_authn_token="$(openssl rand -hex 32)"
  judge0_authz_token="$(openssl rand -hex 32)"
  judge0_redis_password="$(openssl rand -hex 32)"
  judge0_postgres_password="$(openssl rand -hex 32)"
  {
    printf 'JUDGE0_AUTHN_TOKEN=%s\n' "${judge0_authn_token}"
    printf 'JUDGE0_AUTHZ_TOKEN=%s\n' "${judge0_authz_token}"
    printf 'JUDGE0_REDIS_PASSWORD=%s\n' "${judge0_redis_password}"
    printf 'JUDGE0_POSTGRES_PASSWORD=%s\n' "${judge0_postgres_password}"
  } > "${judge0_env}"
  chmod 600 "${judge0_env}"
else
  # This file contains only generated hex values and is never printed.
  set -a
  # shellcheck disable=SC1090
  source "${judge0_env}"
  set +a
  judge0_authn_token="${JUDGE0_AUTHN_TOKEN:?missing Judge0 authn token}"
  judge0_authz_token="${JUDGE0_AUTHZ_TOKEN:?missing Judge0 authz token}"
  judge0_redis_password="${JUDGE0_REDIS_PASSWORD:?missing Judge0 Redis password}"
  judge0_postgres_password="${JUDGE0_POSTGRES_PASSWORD:?missing Judge0 PostgreSQL password}"
fi

set_env_value "${backend_env}" JUDGE0_API_URL "http://127.0.0.1:2358"
set_env_value "${backend_env}" JUDGE0_AUTHN_HEADER "X-Auth-Token"
set_env_value "${backend_env}" JUDGE0_AUTHN_TOKEN "${judge0_authn_token}"
set_env_value "${backend_env}" JUDGE0_AUTHZ_HEADER "X-Auth-User"
set_env_value "${backend_env}" JUDGE0_AUTHZ_TOKEN "${judge0_authz_token}"
set_env_value "${backend_env}" JUDGE0_ENABLED "false"

set_env_value "${backend_env}" PADDLEOCR_URL "http://127.0.0.1:8090"
set_env_value "${backend_env}" PADDLEOCR_REQUIRED_FOR_PDF "true"
set_env_value "${backend_env}" PADDLEOCR_TIMEOUT_S "300"
set_env_value "${backend_env}" PADDLEOCR_MAX_PAGES "50"

set_env_value "${backend_env}" GRAPHRAG_ENABLED "false"
set_env_value "${backend_env}" GRAPHRAG_WORKER_PYTHON "${app_root}/backend/.venv-graphrag/bin/python"
set_env_value "${backend_env}" GRAPHRAG_EMBEDDING_LOCAL_PATH "./models/bge-small-zh-v1.5"
set_env_value "${backend_env}" GRAPHRAG_RUN_TIMEOUT_SECONDS "1800"
set_env_value "${backend_env}" GRAPHRAG_MAX_INPUT_TOKENS "25000"
set_env_value "${backend_env}" GRAPHRAG_ESTIMATED_INPUT_COST_USD_PER_MILLION_TOKENS "30"
set_env_value "${backend_env}" GRAPHRAG_MAX_ESTIMATED_COST_USD "0.70"
set_env_value "${backend_env}" GRAPHRAG_MAX_ESTIMATED_COST "0.70"

chmod 600 "${backend_env}" "${judge0_env}"
echo "Runtime configuration prepared; Judge0 and GraphRAG remain disabled"

#!/usr/bin/env bash
set -euo pipefail

readonly app_root="/opt/smartcarb-git"
readonly backend_root="${app_root}/backend"
readonly backend_env="${backend_root}/.env"
readonly judge0_root="${app_root}/deploy/judge0"
readonly judge0_env="${judge0_root}/.env"
readonly compose_base="${judge0_root}/docker-compose.yml"
readonly compose_override="${judge0_root}/docker-compose.privileged-worker.yml"
readonly service_name="smartcarb-backend.service"

test -f "${backend_env}"
test -f "${judge0_env}"
test -f "${compose_base}"
test -f "${compose_override}"
umask 077

compose=(
  docker compose
  --env-file "${judge0_env}"
  -f "${compose_base}"
  -f "${compose_override}"
)

backend_backup=""
rollback() {
  local exit_code=$?
  trap - EXIT
  if [[ -n "${backend_backup}" && -f "${backend_backup}" ]]; then
    cp -p "${backend_backup}" "${backend_env}"
    systemctl restart "${service_name}" || true
  fi
  "${compose[@]}" down || true
  echo "Judge0 enablement failed; backend flag restored and containers stopped (volumes retained)" >&2
  exit "${exit_code}"
}
trap rollback EXIT

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

"${compose[@]}" config >/dev/null
"${compose[@]}" up -d

server_id="$("${compose[@]}" ps -q server)"
worker_id="$("${compose[@]}" ps -q worker)"
db_id="$("${compose[@]}" ps -q db)"
redis_id="$("${compose[@]}" ps -q redis)"
test -n "${server_id}"
test -n "${worker_id}"
test -n "${db_id}"
test -n "${redis_id}"

test "$(docker inspect -f '{{.HostConfig.Privileged}}' "${worker_id}")" = "true"
for container_id in "${server_id}" "${db_id}" "${redis_id}"; do
  test "$(docker inspect -f '{{.HostConfig.Privileged}}' "${container_id}")" = "false"
done

# Fail closed when Compose did not apply the host-side resource ceilings.
test "$(docker inspect -f '{{.HostConfig.Memory}}' "${server_id}")" -eq 536870912
test "$(docker inspect -f '{{.HostConfig.Memory}}' "${worker_id}")" -eq 1610612736
test "$(docker inspect -f '{{.HostConfig.Memory}}' "${db_id}")" -eq 536870912
test "$(docker inspect -f '{{.HostConfig.Memory}}' "${redis_id}")" -eq 134217728
for container_id in "${server_id}" "${worker_id}" "${db_id}" "${redis_id}"; do
  test "$(docker inspect -f '{{.HostConfig.PidsLimit}}' "${container_id}")" -gt 0
done

test "$(docker port "${server_id}" 2358/tcp)" = "127.0.0.1:2358"
worker_networks="$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' "${worker_id}" | xargs)"
test "${worker_networks}" = "judge0_net"

set -a
# shellcheck disable=SC1090
source "${judge0_env}"
set +a

for _attempt in $(seq 1 60); do
  if curl -fsS --max-time 5 \
    -H "X-Auth-Token: ${JUDGE0_AUTHN_TOKEN:?}" \
    -H "X-Auth-User: ${JUDGE0_AUTHZ_TOKEN:?}" \
    http://127.0.0.1:2358/system_info >/dev/null; then
    break
  fi
  sleep 2
done
curl -fsS --max-time 5 \
  -H "X-Auth-Token: ${JUDGE0_AUTHN_TOKEN:?}" \
  -H "X-Auth-User: ${JUDGE0_AUTHZ_TOKEN:?}" \
  http://127.0.0.1:2358/system_info >/dev/null

(
  cd "${judge0_root}"
  /usr/bin/python3 smoke_test.py
)

backend_backup="${backend_env}.before-judge0-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "${backend_env}" "${backend_backup}"
chmod 600 "${backend_backup}"
set_env_value "${backend_env}" JUDGE0_ENABLED true
chmod 600 "${backend_env}"

systemctl restart "${service_name}"
for _attempt in $(seq 1 45); do
  if curl -fsS --max-time 5 http://127.0.0.1:8000/ >/dev/null; then
    trap - EXIT
    echo "Judge0 privileged Worker enabled; synthetic isolation smoke and backend health passed"
    exit 0
  fi
  sleep 2
done

echo "Backend health check did not recover after enabling Judge0" >&2
exit 1

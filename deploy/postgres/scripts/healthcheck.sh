#!/usr/bin/env sh
set -eu

: "${POSTGRES_CONTAINER_NAME:=smartcarb-postgres}"
: "${POSTGRES_DB:=ai_course}"
: "${POSTGRES_BACKUP_DIR:?POSTGRES_BACKUP_DIR is required}"
: "${POSTGRES_BACKUP_MAX_AGE_SECONDS:=90000}"

umask 077
docker exec "$POSTGRES_CONTAINER_NAME" sh -ceu '
  PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "
    SELECT json_build_object(
      '\''database'\'', current_database(),
      '\''connections'\'', (SELECT count(*) FROM pg_stat_activity),
      '\''max_connections'\'', current_setting('\''max_connections'\''),
      '\''slow_query_log_ms'\'', current_setting('\''log_min_duration_statement'\''),
      '\''pg_stat_statements_enabled'\'', EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = '\''pg_stat_statements'\''
      ),
      '\''tracked_statement_count'\'', (SELECT count(*) FROM pg_stat_statements),
      '\''timezone'\'', current_setting('\''TimeZone'\'')
    )::text;"
'

df -Pk "$POSTGRES_BACKUP_DIR" | awk 'NR == 2 {printf "{\"backup_filesystem_available_kib\":%s,\"backup_filesystem_used_percent\":\"%s\"}\n", $4, $5}'

latest_dump="$(find "$POSTGRES_BACKUP_DIR" -maxdepth 1 -type f -name "${POSTGRES_DB}_*.dump" -printf '%T@\n' | sort -nr | head -n 1)"
if [ -z "$latest_dump" ]; then
  printf '%s\n' '{"backup":"missing"}' >&2
  exit 1
fi
backup_age_seconds="$(( $(date -u +%s) - ${latest_dump%.*} ))"
printf '{"backup_age_seconds":%s,"backup_max_age_seconds":%s}\n' "$backup_age_seconds" "$POSTGRES_BACKUP_MAX_AGE_SECONDS"
if [ "$backup_age_seconds" -gt "$POSTGRES_BACKUP_MAX_AGE_SECONDS" ]; then
  printf '%s\n' '{"backup":"stale"}' >&2
  exit 1
fi

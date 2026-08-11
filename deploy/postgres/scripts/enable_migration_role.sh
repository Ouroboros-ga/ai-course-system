#!/usr/bin/env sh
set -eu

: "${POSTGRES_CONTAINER_NAME:=smartcarb-postgres}"
: "${POSTGRES_DB:=ai_course}"
: "${AI_COURSE_MIGRATION_DB_USER:?AI_COURSE_MIGRATION_DB_USER is required}"

# The migration role needs this temporary capability only because the transfer
# command imports cyclic legacy references with session_replication_role=replica.
# It must be disabled again by disable_migration_role.sh before user traffic.
docker exec -i \
  -e MIGRATION_DB_USER="$AI_COURSE_MIGRATION_DB_USER" \
  "$POSTGRES_CONTAINER_NAME" sh -ceu '
  PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v migration_user="$MIGRATION_DB_USER"
' <<'SQL'
ALTER ROLE :"migration_user" LOGIN SUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
SQL

#!/usr/bin/env sh
set -eu

: "${POSTGRES_CONTAINER_NAME:=smartcarb-postgres}"
: "${POSTGRES_DB:=ai_course}"
: "${AI_COURSE_MIGRATION_DB_USER:?AI_COURSE_MIGRATION_DB_USER is required}"

# Keep ownership of the migrated tables for default privilege handling, while
# removing all login and elevated capabilities after the maintenance window.
docker exec -i \
  -e MIGRATION_DB_USER="$AI_COURSE_MIGRATION_DB_USER" \
  "$POSTGRES_CONTAINER_NAME" sh -ceu '
  PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v migration_user="$MIGRATION_DB_USER"
' <<'SQL'
ALTER ROLE :"migration_user" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
SQL

#!/bin/sh
set -eu

: "${AI_COURSE_APP_DB_USER:?AI_COURSE_APP_DB_USER is required}"
: "${AI_COURSE_APP_DB_PASSWORD:?AI_COURSE_APP_DB_PASSWORD is required}"
: "${AI_COURSE_MIGRATION_DB_USER:?AI_COURSE_MIGRATION_DB_USER is required}"
: "${AI_COURSE_MIGRATION_DB_PASSWORD:?AI_COURSE_MIGRATION_DB_PASSWORD is required}"

psql --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=db_name="$POSTGRES_DB" \
  --set=app_user="$AI_COURSE_APP_DB_USER" \
  --set=app_password="$AI_COURSE_APP_DB_PASSWORD" \
  --set=migration_user="$AI_COURSE_MIGRATION_DB_USER" \
  --set=migration_password="$AI_COURSE_MIGRATION_DB_PASSWORD" <<'SQL'
CREATE ROLE :"app_user" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'app_password';
CREATE ROLE :"migration_user" LOGIN SUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'migration_password';
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db_name" TO :"app_user";
GRANT CONNECT ON DATABASE :"db_name" TO :"migration_user";
GRANT USAGE ON SCHEMA public TO :"app_user";
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SQL

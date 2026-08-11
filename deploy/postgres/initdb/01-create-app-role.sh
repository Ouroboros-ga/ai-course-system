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
# PG15+ 中 public schema 默认对 PUBLIC 授予 USAGE（无 CREATE）。
# 外键检查（RI）的 FOR KEY SHARE 权限计算依赖该 PUBLIC USAGE；
# 仅给应用用户显式 USAGE 会在写引用 courses/users 等父表的行时
# 报 "permission denied for schema public"。故 REVOKE 后必须恢复 USAGE。
GRANT USAGE ON SCHEMA public TO PUBLIC;
GRANT CONNECT ON DATABASE :"db_name" TO :"app_user";
GRANT CONNECT ON DATABASE :"db_name" TO :"migration_user";
GRANT USAGE ON SCHEMA public TO :"app_user";
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SQL

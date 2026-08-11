#!/usr/bin/env sh
set -eu

: "${POSTGRES_CONTAINER_NAME:=smartcarb-postgres}"
: "${POSTGRES_DB:=ai_course}"
: "${POSTGRES_BACKUP_DIR:?POSTGRES_BACKUP_DIR is required}"

umask 077
mkdir -p "$POSTGRES_BACKUP_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
temporary="$POSTGRES_BACKUP_DIR/${POSTGRES_DB}_${timestamp}.dump.tmp"
final="$POSTGRES_BACKUP_DIR/${POSTGRES_DB}_${timestamp}.dump"

# The password remains inside the already-running container environment.  No
# DSN or secret is written to this script's output or backup filename.
docker exec "$POSTGRES_CONTAINER_NAME" sh -ceu '
  PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"
' > "$temporary"
mv "$temporary" "$final"
sha256sum "$final" > "$final.sha256"

# Retain the newest seven daily dumps.  On Sundays, retain an additional weekly
# copy for four weeks so daily retention cannot remove the monthly recovery
# points.  The copy stays on the same local filesystem; off-host replication is
# deliberately a separate operational responsibility.
if [ "$(date -u +%u)" = "7" ]; then
  weekly_dir="$POSTGRES_BACKUP_DIR/weekly"
  mkdir -p "$weekly_dir"
  weekly_dump="$weekly_dir/$(basename "$final")"
  cp "$final" "$weekly_dump"
  cp "$final.sha256" "$weekly_dump.sha256"
  find "$weekly_dir" -maxdepth 1 -type f -name "${POSTGRES_DB}_*.dump" -mtime +28 -delete
  find "$weekly_dir" -maxdepth 1 -type f -name "${POSTGRES_DB}_*.dump.sha256" -mtime +28 -delete
fi

# Daily backups are kept for seven days.
find "$POSTGRES_BACKUP_DIR" -maxdepth 1 -type f -name "${POSTGRES_DB}_*.dump" -mtime +7 -delete
find "$POSTGRES_BACKUP_DIR" -maxdepth 1 -type f -name "${POSTGRES_DB}_*.dump.sha256" -mtime +7 -delete
printf '%s\n' "$final"

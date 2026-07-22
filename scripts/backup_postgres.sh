#!/usr/bin/env bash
# Dumps the factory Postgres database to a timestamped, gzip-compressed file
# and prunes backups older than $RETENTION_DAYS. Meant to run via host cron
# on the VPS (see DEPLOY.md) — not inside the postgres container itself, so
# it survives `docker compose down`.
#
# Usage: ./scripts/backup_postgres.sh [backup_dir]
# Cron example (daily at 03:15):
#   15 3 * * * /path/to/ai-company/scripts/backup_postgres.sh >> /var/log/factory-backup.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${1:-$PROJECT_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

# Load POSTGRES_* from .env without executing arbitrary content.
if [ -f "$PROJECT_DIR/.env" ]; then
    POSTGRES_USER=$(grep -E '^POSTGRES_USER=' "$PROJECT_DIR/.env" | cut -d= -f2- || true)
    POSTGRES_DB=$(grep -E '^POSTGRES_DB=' "$PROJECT_DIR/.env" | cut -d= -f2- || true)
fi
POSTGRES_USER="${POSTGRES_USER:-factory}"
POSTGRES_DB="${POSTGRES_DB:-factory}"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUT_FILE="$BACKUP_DIR/factory-$TIMESTAMP.sql.gz"

echo "Backing up $POSTGRES_DB to $OUT_FILE"
docker compose -f "$PROJECT_DIR/docker-compose.yml" exec -T postgres \
    pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$OUT_FILE"

echo "Pruning backups older than $RETENTION_DAYS days"
find "$BACKUP_DIR" -name 'factory-*.sql.gz' -mtime "+$RETENTION_DAYS" -delete

echo "Done: $OUT_FILE ($(du -h "$OUT_FILE" | cut -f1))"

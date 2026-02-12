#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/rob/.openclaw/workspace/blofin-stack"
DB="$ROOT/data/blofin_monitor.db"
BACKUP_DIR="$ROOT/backups"
TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR"

if [[ ! -f "$DB" ]]; then
  echo "DB not found: $DB" >&2
  exit 1
fi

OUT="$BACKUP_DIR/blofin_monitor_${TS}.sqlite3"
cp "$DB" "$OUT"
if [[ -f "$DB-wal" ]]; then cp "$DB-wal" "$OUT-wal"; fi
if [[ -f "$DB-shm" ]]; then cp "$DB-shm" "$OUT-shm"; fi

gzip -f "$OUT"
if [[ -f "$OUT-wal" ]]; then gzip -f "$OUT-wal"; fi
if [[ -f "$OUT-shm" ]]; then gzip -f "$OUT-shm"; fi

echo "Backup created: ${OUT}.gz"

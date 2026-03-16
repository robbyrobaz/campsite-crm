#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /path/to/blofin_monitor_YYYYMMDDTHHMMSSZ.sqlite3.gz" >&2
  exit 1
fi

SRC="$1"
ROOT="/home/rob/.openclaw/workspace/blofin-stack"
DB="$ROOT/data/blofin_monitor.db"
TMP=$(mktemp)

if [[ ! -f "$SRC" ]]; then
  echo "Backup not found: $SRC" >&2
  exit 1
fi

gunzip -c "$SRC" > "$TMP"

systemctl --user stop blofin-stack-api.service blofin-stack-ingestor.service || true
mv "$TMP" "$DB"
rm -f "$DB-wal" "$DB-shm"
systemctl --user start blofin-stack-ingestor.service blofin-stack-api.service || true

echo "Restored DB to: $DB"

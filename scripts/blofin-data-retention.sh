#!/usr/bin/env bash
set -euo pipefail

# ── Blofin Data Retention ───────────────────────────────────────────
# Runs daily to keep disk usage in check:
#   1. Delete raw JSONL files older than 1 day (redundant with DB)
#   2. Prune ticks older than 14 days from the database
#   3. Prune signals/confirmed_signals older than 30 days
# ────────────────────────────────────────────────────────────────────

DATA_DIR="/home/rob/.openclaw/workspace/blofin-stack/data"
DB="$DATA_DIR/blofin_monitor.db"
DB_TIMEOUT=300  # seconds for DB operations (increased)

echo "Starting blofin data retention at $(date)"
echo "DATA_DIR: $DATA_DIR"
echo "DB: $DB"
echo "DB_TIMEOUT: $DB_TIMEOUT"

# 1. Delete raw JSONL files older than 1 day
echo "Step 1: Deleting raw JSONL files older than 1 day"
find "$DATA_DIR" -name 'raw_*.jsonl' -mtime +1 -delete -print 2>/dev/null | \
  while read f; do echo "Deleted old JSONL: $f"; done
echo "Step 1 complete"

# 2. Prune old ticks (keep 14 days)
if [[ -f "$DB" ]]; then
  echo "Step 2: Pruning ticks older than 14 days"
  cutoff_ms=$(python3 -c "import time; print(int((time.time() - 14*86400) * 1000))")
  echo "Cutoff ms: $cutoff_ms"
  deleted=$(timeout $DB_TIMEOUT python3 -c "
import sqlite3
import sys
try:
    db = sqlite3.connect('$DB', timeout=$DB_TIMEOUT)
    cur = db.cursor()
    cur.execute('DELETE FROM ticks WHERE ts_ms < $cutoff_ms')
    print(cur.rowcount)
    db.commit()
    db.close()
except sqlite3.OperationalError as e:
    print('0', file=sys.stderr)
    sys.exit(1)
")
  echo "Pruned $deleted ticks older than 14 days"
  echo "Step 2 complete"

  # 3. Prune old signals (keep 30 days)
  echo "Step 3: Pruning signals/confirmed_signals/strategy_scores older than 30 days"
  cutoff_30d_ms=$(python3 -c "import time; print(int((time.time() - 30*86400) * 1000))")
  echo "Cutoff 30d ms: $cutoff_30d_ms"
  for table in signals confirmed_signals strategy_scores; do
    echo "Processing table: $table"
    deleted=$(timeout $DB_TIMEOUT python3 -c "
import sqlite3
import sys
try:
    db = sqlite3.connect('$DB', timeout=$DB_TIMEOUT)
    cur = db.cursor()
    cur.execute('DELETE FROM $table WHERE ts_ms < $cutoff_30d_ms')
    print(cur.rowcount)
    db.commit()
    db.close()
except sqlite3.OperationalError as e:
    print('0', file=sys.stderr)
    sys.exit(1)
")
    echo "Pruned $deleted rows from $table older than 30 days"
  done
  echo "Step 3 complete"
else
  echo "Database file not found: $DB"
fi

echo "Data retention complete at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

#!/usr/bin/env bash
set -euo pipefail

# ── Blofin Data Retention ───────────────────────────────────────────
# Runs daily to keep disk usage in check:
#   1. Delete raw JSONL files older than 1 day (redundant with DB)
#   2. Prune ticks older than 14 days from the database (batched)
#   3. Prune signals/confirmed_signals older than 30 days (batched)
#
# BATCHED DELETE strategy: delete BATCH_SIZE rows at a time with a
# short sleep between batches. This prevents a single 5+ minute write
# lock that blocks the daily pipeline and causes cascade failures.
# ────────────────────────────────────────────────────────────────────

DATA_DIR="/home/rob/.openclaw/workspace/blofin-stack/data"
DB="$DATA_DIR/blofin_monitor.db"

echo "Starting blofin data retention at $(date)"
echo "DATA_DIR: $DATA_DIR"
echo "DB: $DB"

# 1. Delete raw JSONL files older than 1 day
echo "Step 1: Deleting raw JSONL files older than 1 day"
find "$DATA_DIR" -name 'raw_*.jsonl' -mtime +1 -delete -print 2>/dev/null | \
  while read f; do echo "Deleted old JSONL: $f"; done
echo "Step 1 complete"

# 2. Prune old ticks (keep 14 days) — batched to avoid long write locks
if [[ -f "$DB" ]]; then
  echo "Step 2: Pruning ticks older than 14 days (batched)"
  cutoff_ms=$(python3 -c "import time; print(int((time.time() - 14*86400) * 1000))")
  echo "Cutoff ms: $cutoff_ms"
  python3 << PYEOF
import sqlite3
import time
import sys

DB = "$DB"
cutoff_ms = $cutoff_ms
BATCH = 50_000
SLEEP = 0.5   # half-second between batches so ingestor can write

db = sqlite3.connect(DB, timeout=60)
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA synchronous=NORMAL")
total = 0
while True:
    try:
        cur = db.execute(
            "DELETE FROM ticks WHERE rowid IN "
            "(SELECT rowid FROM ticks WHERE ts_ms < ? LIMIT ?)",
            (cutoff_ms, BATCH)
        )
        n = cur.rowcount
        db.commit()
        total += n
        print(f"  Deleted {n} ticks (total so far: {total:,})", flush=True)
        if n < BATCH:
            break
        time.sleep(SLEEP)
    except sqlite3.OperationalError as e:
        print(f"  DB locked, retrying in 5s: {e}", file=sys.stderr)
        time.sleep(5)
db.close()
print(f"Step 2 complete — pruned {total:,} ticks older than 14 days")
PYEOF
  echo "Step 2 done"

  # 3. Prune old signals (keep 30 days) — also batched
  echo "Step 3: Pruning signals/confirmed_signals/strategy_scores older than 30 days"
  cutoff_30d_ms=$(python3 -c "import time; print(int((time.time() - 30*86400) * 1000))")
  echo "Cutoff 30d ms: $cutoff_30d_ms"
  for table in signals confirmed_signals strategy_scores; do
    echo "Processing table: $table"
    python3 << PYEOF2
import sqlite3
import time
import sys

DB = "$DB"
cutoff_ms = $cutoff_30d_ms
table = "$table"
BATCH = 50_000
SLEEP = 0.5

db = sqlite3.connect(DB, timeout=60)
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA synchronous=NORMAL")
total = 0
while True:
    try:
        cur = db.execute(
            f"DELETE FROM {table} WHERE rowid IN "
            f"(SELECT rowid FROM {table} WHERE ts_ms < ? LIMIT ?)",
            (cutoff_ms, BATCH)
        )
        n = cur.rowcount
        db.commit()
        total += n
        if n < BATCH:
            break
        time.sleep(SLEEP)
    except sqlite3.OperationalError as e:
        print(f"  DB locked, retrying in 5s: {e}", file=sys.stderr)
        time.sleep(5)
db.close()
print(f"  Pruned {total:,} rows from {table}")
PYEOF2
  done
  echo "Step 3 complete"
else
  echo "Database file not found: $DB"
fi

echo "Data retention complete at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

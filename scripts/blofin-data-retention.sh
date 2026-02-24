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

# 1. Delete raw JSONL files older than 1 day
find "$DATA_DIR" -name 'raw_*.jsonl' -mtime +1 -delete -print 2>/dev/null | \
  while read f; do echo "Deleted old JSONL: $f"; done

# 2. Prune old ticks (keep 14 days)
if [[ -f "$DB" ]]; then
  cutoff_ms=$(python3 -c "import time; print(int((time.time() - 14*86400) * 1000))")
  deleted=$(python3 -c "
import sqlite3
db = sqlite3.connect('$DB')
cur = db.cursor()
cur.execute('DELETE FROM ticks WHERE ts_ms < $cutoff_ms')
print(cur.rowcount)
db.commit()
db.close()
")
  echo "Pruned $deleted ticks older than 14 days"

  # 3. Prune old signals (keep 30 days)
  cutoff_30d_ms=$(python3 -c "import time; print(int((time.time() - 30*86400) * 1000))")
  for table in signals confirmed_signals strategy_scores; do
    deleted=$(python3 -c "
import sqlite3
db = sqlite3.connect('$DB')
cur = db.cursor()
cur.execute('DELETE FROM $table WHERE ts_ms < $cutoff_30d_ms')
print(cur.rowcount)
db.commit()
db.close()
")
    echo "Pruned $deleted rows from $table older than 30 days"
  done
fi

echo "Data retention complete at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

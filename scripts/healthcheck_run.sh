#!/usr/bin/env bash
# Blofin pipeline health check: zero-AI by default.
# Only exits 0 (needs LLM alert) if auto-heal failed.
# Exit codes:
#   0 = needs LLM (status still bad after auto-heal)
#   1 = healthy or healed (NO_REPLY)
#   2 = error

set -euo pipefail

LOCK_FILE="/tmp/openclaw-healthcheck.lock"
LOCK_TTL=600
BLOFIN_DIR="$HOME/.openclaw/workspace/blofin-stack"
LOG_DIR="$BLOFIN_DIR/data/logs"
LOG_FILE="$LOG_DIR/healthcheck.log"
VENV="$BLOFIN_DIR/.venv/bin/python"

mkdir -p "$LOG_DIR"

# --- Lock check ---
if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(python3 -c "import json; print(json.load(open('$LOCK_FILE')).get('pid',0))" 2>/dev/null || echo 0)
    LOCK_TS=$(python3 -c "import json,time; print(int(time.time()-json.load(open('$LOCK_FILE')).get('ts',0)))" 2>/dev/null || echo 9999)
    if kill -0 "$LOCK_PID" 2>/dev/null && [ "$LOCK_TS" -lt "$LOCK_TTL" ]; then
        echo "LOCKED" >&2
        exit 1
    fi
    rm -f "$LOCK_FILE"
fi
python3 -c "import json,os,time; json.dump({'pid':os.getpid(),'ts':time.time()}, open('$LOCK_FILE','w'))"
trap 'rm -f "$LOCK_FILE"' EXIT

# --- Check processes ---
INGESTOR_RUNNING=false
PAPER_RUNNING=false
API_RUNNING=false

pgrep -f "ingestor.py" >/dev/null 2>&1 && INGESTOR_RUNNING=true
pgrep -f "paper_engine.py" >/dev/null 2>&1 && PAPER_RUNNING=true
pgrep -f "api_server.py" >/dev/null 2>&1 && API_RUNNING=true

# --- Check data recency ---
RECENCY=$($VENV -c "
import sqlite3, time, json
con = sqlite3.connect('$BLOFIN_DIR/data/blofin_monitor.db')
now_ms = int(time.time() * 1000)
results = {}
for table, col in [('ticks','ts_ms'), ('signals','ts_ms'), ('confirmed_signals','ts_ms'), ('paper_trades','opened_ts_ms')]:
    try:
        cur = con.execute(f'SELECT MAX({col}) FROM {table}')
        val = cur.fetchone()[0]
        results[table] = round((now_ms - (val or 0)) / 60000, 1) if val else -1
    except:
        results[table] = -1
# Counts in last 30 min
for table in ['signals', 'confirmed_signals', 'paper_trades']:
    col = 'opened_ts_ms' if table == 'paper_trades' else 'ts_ms'
    try:
        cur = con.execute(f'SELECT COUNT(*) FROM {table} WHERE {col} > ?', (now_ms - 1800000,))
        results[table + '_30m'] = cur.fetchone()[0]
    except:
        results[table + '_30m'] = 0
con.close()
print(json.dumps(results))
" 2>/dev/null) || { echo "$(date -Iseconds) ERROR: recency query failed" >> "$LOG_FILE"; exit 2; }

TICKS_AGE=$(echo "$RECENCY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ticks',-1))")
SIGNALS_AGE=$(echo "$RECENCY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('signals',-1))")
CONFIRMED_AGE=$(echo "$RECENCY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('confirmed_signals',-1))")

# --- Determine status ---
STATUS="HEALTHY"

if [ "$INGESTOR_RUNNING" = false ] || [ "$PAPER_RUNNING" = false ]; then
    STATUS="DOWN"
elif python3 -c "exit(0 if $TICKS_AGE > 5 or $TICKS_AGE < 0 else 1)"; then
    STATUS="DOWN"
elif python3 -c "exit(0 if $SIGNALS_AGE > 20 or $CONFIRMED_AGE > 30 else 1)"; then
    STATUS="DEGRADED"
fi

STATUS_BEFORE="$STATUS"
ACTION="none"

# --- Auto-heal ---
if [ "$STATUS" = "DOWN" ]; then
    ACTION="restart_ingestor_and_paper"
    systemctl --user restart blofin-stack-ingestor.service 2>/dev/null || true
    systemctl --user restart blofin-stack-paper.service 2>/dev/null || true
    sleep 20
elif [ "$STATUS" = "DEGRADED" ]; then
    ACTION="restart_ingestor"
    systemctl --user restart blofin-stack-ingestor.service 2>/dev/null || true
    sleep 20
fi

# --- Re-check after heal ---
if [ "$ACTION" != "none" ]; then
    INGESTOR_RUNNING=false
    PAPER_RUNNING=false
    pgrep -f "ingestor.py" >/dev/null 2>&1 && INGESTOR_RUNNING=true
    pgrep -f "paper_engine.py" >/dev/null 2>&1 && PAPER_RUNNING=true

    RECENCY2=$($VENV -c "
import sqlite3, time, json
con = sqlite3.connect('$BLOFIN_DIR/data/blofin_monitor.db')
now_ms = int(time.time() * 1000)
results = {}
for table, col in [('ticks','ts_ms'), ('signals','ts_ms'), ('confirmed_signals','ts_ms')]:
    try:
        cur = con.execute(f'SELECT MAX({col}) FROM {table}')
        val = cur.fetchone()[0]
        results[table] = round((now_ms - (val or 0)) / 60000, 1) if val else -1
    except:
        results[table] = -1
con.close()
print(json.dumps(results))
" 2>/dev/null) || RECENCY2="$RECENCY"

    TICKS_AGE2=$(echo "$RECENCY2" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ticks',-1))")

    if [ "$INGESTOR_RUNNING" = true ] && [ "$PAPER_RUNNING" = true ] && python3 -c "exit(0 if $TICKS_AGE2 <= 5 and $TICKS_AGE2 >= 0 else 1)"; then
        STATUS="HEALTHY"
    fi
fi

# --- Log ---
echo "$(date -Iseconds) before=$STATUS_BEFORE after=$STATUS action=$ACTION ticks=${TICKS_AGE}m signals=${SIGNALS_AGE}m confirmed=${CONFIRMED_AGE}m" >> "$LOG_FILE"

# --- Output ---
if [ "$STATUS" = "HEALTHY" ]; then
    exit 1  # no LLM needed
else
    # LLM needed to draft alert
    echo "{\"status_before\":\"$STATUS_BEFORE\",\"status_after\":\"$STATUS\",\"action\":\"$ACTION\",\"ticks_age_min\":$TICKS_AGE,\"signals_age_min\":$SIGNALS_AGE,\"confirmed_age_min\":$CONFIRMED_AGE}"
    exit 0
fi

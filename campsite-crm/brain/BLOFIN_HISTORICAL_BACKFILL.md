# Blofin Historical Data Backfill - Active Job

**Started:** 2026-03-15 18:14 MST  
**Current Status:** IN PROGRESS (as of 2026-03-16 05:40 MST)  
**Progress:** 67/469 symbols complete (14.3%)  
**ETA:** Tuesday evening Mar 18 - Wednesday morning Mar 19, 2026  

---

## What This Is

A 70-hour background job downloading 365 days of 1-minute historical candle data for all 469 Blofin USDT perpetual futures symbols.

**Total data:** ~247 million candles (469 symbols × 525,600 candles each)  
**Storage:** `/mnt/data/blofin_tickers/raw/{SYMBOL}/tickers/*.parquet`  
**Current size:** 683 MB (will grow to 15-25 GB when complete)  

---

## Why It Matters

- **Backtesting:** DuckDB reads these Parquet files directly — no migration needed
- **Strategy validation:** 365 days of data for all crypto pairs
- **ML training:** Historical features for Moonshot v2 and Blofin Stack
- **Research:** Full year of market data for pattern discovery

---

## Current State (2026-03-16 05:40 MST)

**Process:** PID 1743860  
**Started:** 2026-03-16 05:37 MST (restarted after outage)  
**Log:** `blofin-stack/logs/backfill_FINAL_RESTART_20260316_0537.log`  
**Symbols completed:** 67/469 (14.3%)  
**Data collected:** 29.3M candles, 683 MB  
**Rate:** ~1 symbol per 10-15 minutes  
**Remaining time:** ~67-100 hours  

**Most recently completed symbols:**
- BTC-USDT (just completed 05:36 MST)
- BAS-USDT (265,000 candles, 185 days)
- BARD-USDT (257,628 candles, 180 days)
- BANK-USDT (476,875 candles, 332 days)

---

## Watchdog Monitoring

**Cron ID:** `3128d9ad-1e64-47ba-b73f-7c5cc93aa67c`  
**Schedule:** Every 10 minutes  
**Model:** Haiku (low cost)  
**Auto-restart:** YES (if process dead and <469 symbols complete)  
**Progress updates:** Every 6 hours (36 watchdog cycles)  

**What it checks:**
1. Process alive (`ps aux | grep backfill_historical_tickers.py`)
2. Log freshness (must be written to within last 15 minutes)
3. If dead OR stale → count symbols complete → restart if <469

**Alert on restart:** Sends message with current progress, PID, timestamp

---

## Incident History

### 2026-03-16 05:30 MST - 3.5 Hour Outage
**What happened:** Process died at 02:10 MST, undetected until Rob asked at 05:30 MST  
**Root cause:** NO watchdog existed — Jarvis completely failed to monitor this critical 70-hour job  
**Impact:** Lost 3.5 hours of progress (BAS_USDT stuck at batch 184)  
**Fix:** Created watchdog cron (every 10 min, auto-restart), restarted backfill at 05:37 MST  
**Lesson:** ALL long-running jobs (>1 hour) MUST have a watchdog. No exceptions.  

---

## How to Check Progress

### Quick check
```bash
# Count completed symbols
find /mnt/data/blofin_tickers/raw -type d -name "tickers" | wc -l

# Check if process is running
ps aux | grep backfill_historical_tickers.py | grep -v grep

# Disk usage
du -sh /mnt/data/blofin_tickers/
```

### Detailed progress
```bash
cd blofin-stack
.venv/bin/python3 << 'EOF'
import duckdb
con = duckdb.connect(':memory:')
result = con.execute("""
    SELECT 
        COUNT(DISTINCT symbol) as symbols,
        COUNT(*) as total_candles,
        MIN(ts_iso) as earliest,
        MAX(ts_iso) as latest
    FROM read_parquet('/mnt/data/blofin_tickers/raw/*/tickers/*.parquet')
""").fetchone()
print(f"Symbols: {result[0]}/469")
print(f"Candles: {result[1]:,}")
print(f"Range: {result[2]} → {result[3]}")
EOF
```

### Check log (last 20 lines)
```bash
tail -20 blofin-stack/logs/backfill_FINAL_RESTART_20260316_0537.log
```

---

## What Happens After Completion

### 1. Verification (automated in script)
- All 469 symbols present
- Date ranges correct
- No corrupted Parquet files

### 2. Ready for Use
**DuckDB queries read Parquet directly** — no migration needed.

Example query:
```sql
SELECT 
    symbol,
    DATE_TRUNC('hour', ts_iso::TIMESTAMP) as hour,
    AVG(last_price) as avg_price,
    SUM(vol_24h_contracts) as total_volume
FROM read_parquet('/mnt/data/blofin_tickers/raw/*/tickers/*.parquet')
WHERE symbol IN ('BTC-USDT', 'ETH-USDT', 'SOL-USDT')
  AND ts_iso >= '2025-01-01'
GROUP BY symbol, hour
ORDER BY symbol, hour;
```

### 3. Integration Points
- **Blofin Stack backtester:** Point to Parquet files, DuckDB reads directly
- **Moonshot v2:** Can aggregate 1-min → 4H if needed (currently separate SQLite)
- **Strategy research:** Full year of data for pattern discovery

---

## Critical Files

| File | Purpose |
|------|---------|
| `blofin-stack/scripts/backfill_historical_tickers.py` | The main backfill script |
| `blofin-stack/brain/HISTORICAL_BACKFILL_PLAN.md` | Detailed plan + usage docs |
| `blofin-stack/logs/backfill_FINAL_RESTART_20260316_0537.log` | Current run log |
| `/mnt/data/blofin_tickers/raw/{SYMBOL}/tickers/*.parquet` | Output data |
| Watchdog cron: `3128d9ad-1e64-47ba-b73f-7c5cc93aa67c` | Auto-restart monitor |

---

## When Rob Asks About "Historical Data" or "Blofin Backfill"

**This is what he means.** Read this file first, then report:
1. Current progress (symbols complete / 469)
2. Process status (PID, running/dead)
3. ETA to completion
4. Any issues (stale log, disk space, rate limits)

**Never say "I don't know what you're talking about."** This file exists so you always know.

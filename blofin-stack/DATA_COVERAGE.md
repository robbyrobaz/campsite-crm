# Blofin Data Coverage - Important Limitations

## REST API Historical Data Constraint

**Blofin's REST API only returns ~1-2 hours of historical OHLCV data**, regardless of the `since` parameter used.

This means:
- ❌ **Cannot backfill deep historical data** (e.g., 7 days) via REST API
- ✅ **Can only fill small recent gaps** (last 1-2 hours) when websocket has downtime
- ✅ **Primary data source is the websocket feed** (`ingestor.py`)

### Tested Evidence
```python
# Requesting data from 7 days ago:
candles = ex.fetch_ohlcv('PEPE/USDT:USDT', '1m', since=7_days_ago, limit=100)
# Result: Only returns most recent 100 minutes (~1.7 hours)
```

## Coverage Strategy

### 1. Live Websocket Feed (Primary)
- `blofin-stack-ingestor.service` - real-time tick ingestion
- Batched symbol subscriptions (8 symbols/batch) to avoid API rejections
- Provides continuous 1-minute resolution data as long as it's running

### 2. Gap Backfill (Secondary)
- `blofin-stack-gapfill.timer` - runs every 30 minutes
- **Only fills gaps within last 24 hours** (`BACKFILL_LOOKBACK_DAYS=1`)
- Limited by Blofin API's shallow historical depth
- Helps recover from brief ingestor downtime

### 3. Expected Coverage
**Realistic goal:**
- **95-99% coverage for last 24 hours** (with healthy websocket)
- **Rolling 7-day window** will only be complete if ingestor has been running continuously

**If ingestor was down:**
- Gaps older than ~2 hours **cannot be backfilled** from Blofin REST API
- You will see permanent coverage gaps for that period

## Dashboard Coverage Metrics

The dashboard (`http://127.0.0.1:8780/`) shows:
- **7-day coverage %** for each symbol
- **Missing minutes** in the rolling window
- **Health status:**
  - `GOOD` = worst symbol ≥99.5%
  - `WARN` = worst symbol ≥97%
  - `CRITICAL` = worst symbol <97%

## Recommendations

1. **Keep `blofin-stack-ingestor.service` running continuously**  
   This is your only source for complete historical data.

2. **Monitor coverage health** via the dashboard  
   Low coverage = ingestor was down recently

3. **Don't expect deep backfills**  
   If you have gaps from days ago, they're permanent.

4. **For long-term storage**, consider:
   - Exporting data periodically to a separate archive
   - Using a dedicated historical data provider if needed

## Files
- `ingestor.py` - Websocket → SQLite (primary data source)
- `historical_backfill.py` - REST gap filler (limited scope)
- `api_server.py` - Dashboard with coverage metrics
- `db.py` - SQLite schema (ticks table)

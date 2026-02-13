# Blofin Data Coverage - Direct REST API Backfill

## Historical Backfill Strategy

**UPDATE 2026-02-12**: The previous assumption that Blofin only returns 1-2 hours of historical data was **incorrect**. The Blofin REST API actually provides full 7-day (and potentially longer) historical OHLCV data. The limitation was in how CCXT was calling the API — it wasn't properly using the pagination parameters.

### Direct Blofin REST API (Full Historical Coverage)
- ✅ **Full 7-day history available** (10,080 minutes at 1m resolution)
- ✅ **Proper backward pagination** using `after` parameter
- ✅ **300 candles per request** (Blofin API limit)
- ✅ **No external exchanges needed** - Blofin has all the data
- ✅ **No authentication required** for market data

### API Details

**Endpoint**: `GET https://openapi.blofin.com/api/v1/market/candles`

**Parameters**:
- `instId`: Instrument ID (e.g., `BTC-USDT`, `PEPE-USDT`)
- `bar`: Timeframe (e.g., `1m`)
- `limit`: Max candles per request (max 300)
- `after`: Pagination cursor - returns candles **older than** this timestamp (milliseconds)

**Pagination behavior** (OKX-style):
- Returns candles in **descending order** (newest first)
- First request (no `after`): Returns most recent 300 candles
- Next request (`after=oldest_ts_from_previous_batch`): Returns 300 candles older than that timestamp
- Continue until reaching desired lookback period or API returns empty response

**Response format**:
```json
{
  "code": "0",
  "data": [
    ["1739389200000", "96000.5", "96100.0", "95900.0", "96050.0", "150", "150000", "14407500000", "0"],
    ...
  ]
}
```
Each candle: `[timestamp_ms, open, high, low, close, vol, volCcy, volCcyQuote, confirm]`
- Close price is at index 4

### Why CCXT Failed

CCXT's `fetch_ohlcv()` method:
- Does not correctly pass the `after` parameter to Blofin
- Uses `since` parameter which Blofin doesn't handle the same way
- Result: Only fetches the most recent batch (~1-2 hours worth)
- **Solution**: Call the Blofin REST API directly using `requests` library

## How the New Backfill Works

The rewritten `historical_backfill.py`:

1. **Check existing coverage** for each symbol in the 7-day window
2. **Skip if ≥99.5% covered** (already complete)
3. **Paginate backward** from now to 7 days ago:
   - Fetch 300 candles per request
   - Use `after` parameter to walk backward
   - Insert only missing minutes (avoid duplicates)
   - Stop when reaching window start or empty response
4. **Rate limiting**:
   - 250ms sleep between API requests
   - 500ms sleep between symbols
5. **Log to `gap_fill_runs`** table with coverage metrics

### Example Output

```
SHIB-USDT: Coverage 20.1% (2023/10081), backfilling...
  Batch 1: Fetched 300 candles (2026-02-13T00:19:00 to 2026-02-12T19:20:00), inserted 1
  Batch 2: Fetched 300 candles (2026-02-12T19:19:00 to 2026-02-12T14:20:00), inserted 0
  ...
  Batch 34: Fetched 300 candles (2026-02-06T03:19:00 to 2026-02-05T22:20:00), inserted 181
  Reached window start, stopping
SHIB-USDT: ✓ Inserted 8058 rows in 34 batches, coverage now 100.0% (10081/10081)
```

## Configuration

### Updated Parameters (.env)
```bash
BACKFILL_TIMEFRAME=1m
BACKFILL_LOOKBACK_HOURS=168          # 7 days = 10,080 minutes
BACKFILL_BATCH_LIMIT=300             # Blofin API max per request
BACKFILL_REQUEST_SLEEP_MS=250        # 250ms between API calls
BACKFILL_SYMBOL_SLEEP_MS=500         # 500ms between symbols
```

**Note**: `BACKFILL_MAX_GAP_MINUTES` is no longer used (the old chunking approach is obsolete).

## Coverage Strategy

### 1. Live Websocket Feed (Primary)
- `blofin-stack-ingestor.service` - real-time tick ingestion
- Batched symbol subscriptions (8 symbols/batch)
- Provides continuous 1-minute resolution data

### 2. Direct REST API Gap Backfill (Secondary)
- `blofin-stack-gapfill.timer` - runs every 30 minutes
- **Fetches up to 7 days directly from Blofin REST API**
- Uses proper backward pagination with `after` parameter
- Only fills actual gaps (skips existing data for efficiency)
- No external exchanges needed

### 3. Expected Coverage

**With healthy websocket + periodic backfill:**
- **99-100% coverage for last 7 days**
- Gaps from ingestor downtime are automatically filled
- Each symbol should reach full coverage within 1-2 backfill runs

**If ingestor was down:**
- Can backfill up to 7 days retroactively using Blofin REST API
- Older data (>7 days) may not be available from Blofin

**New symbols added:**
- Full 7-day backfill on first run (~34 API requests per symbol)
- Subsequent runs only fill small gaps

## Dashboard Coverage Metrics

The dashboard (`http://127.0.0.1:8780/`) shows:
- **7-day coverage %** for each symbol
- **Missing minutes** in the rolling window
- **Data source**: `historical_fill` (direct Blofin REST API)
- **Health status:**
  - `GOOD` = worst symbol ≥99.5%
  - `WARN` = worst symbol ≥97%
  - `CRITICAL` = worst symbol <97%

## Recommendations

1. **Keep `blofin-stack-ingestor.service` running continuously**  
   Real-time websocket is still the most efficient primary data source

2. **Let backfill timer run periodically**  
   Automatically fills gaps from any ingestor downtime

3. **For new symbol additions**:
   - Add to `BLOFIN_SYMBOLS` in `.env`
   - Run `python historical_backfill.py` manually for immediate 7-day fill
   - Timer will maintain coverage going forward

4. **Monitor coverage via dashboard**  
   Low coverage indicates either:
   - Ingestor downtime (check service status)
   - Backfill timer not running
   - Symbol doesn't exist on Blofin (check `gap_fill_runs` for errors)

## Troubleshooting

### Low coverage for specific symbol
- Check if symbol exists on Blofin: `https://openapi.blofin.com/api/v1/market/tickers?instType=SPOT`
- Review `gap_fill_runs` table for error messages
- Verify exact symbol format (e.g., `BTC-USDT`, not `BTC/USDT`)

### Coverage not improving after backfill runs
- Check API response codes in logs
- May be rate-limited (increase `BACKFILL_REQUEST_SLEEP_MS`)
- Symbol may be newly listed on Blofin (historical data not available yet)

### Backfill taking too long
- 32 symbols × 34 batches × 250ms = ~4-5 minutes total
- Adjust `BACKFILL_REQUEST_SLEEP_MS` and `BACKFILL_SYMBOL_SLEEP_MS` if needed
- Already-covered symbols are skipped quickly

## Performance Notes

**API request efficiency**:
- 7 days = 10,080 minutes
- 300 candles per request
- ~34 requests per symbol for full backfill
- ~1 request per symbol for maintenance (just recent gaps)

**Database efficiency**:
- Only inserts missing minutes (deduplication in Python)
- Commits once per symbol (not per candle)
- Indexed queries for fast existing-minute lookups

**Rate limiting**:
- Default 250ms between requests = max ~240 requests/minute
- Well under Blofin's public API limits
- Adjust if you see 429 (rate limit) responses

## Files
- `ingestor.py` - Websocket → SQLite (primary real-time data)
- `historical_backfill.py` - **Rewritten** to use direct Blofin REST API with proper pagination
- `api_server.py` - Dashboard with coverage metrics
- `db.py` - SQLite schema (ticks table with source tracking)

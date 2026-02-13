# Blofin Data Coverage - Multi-Exchange Backfill

## Multi-Exchange Historical Backfill Strategy

**The backfill script now uses multiple data sources** to overcome Blofin's REST API limitations:

### Primary Source: OKX/Bybit (Full 7-day History)
- ✅ **Can backfill up to 7 days** of historical OHLCV data
- ✅ **1000 candles per request** for efficient fetching
- ✅ **Public API** - no authentication required
- ⚠️ **May be geo-restricted** in some locations

### Fallback Source: Blofin REST API (Limited)
- ❌ **Only returns ~1-2 hours** of historical data
- ✅ **Covers Blofin-specific symbols** not on other exchanges
- ✅ **Always available** as last resort

### How It Works

1. **Symbol Mapping**: Converts Blofin format (`BTC-USDT`) to standard format (`BTC/USDT`)
2. **Try External Exchange First**: Attempts OKX, then Bybit for 7-day historical data
3. **Fallback to Blofin**: If symbol not found or external exchange unavailable
4. **Track Provenance**: Each tick is tagged with source (`historical_fill_okx`, `historical_fill_bybit`, or `historical_fill_blofin`)

### Special Cases

**Symbols with prefix:**
- `1000BONK-USDT` → tries `1000BONK/USDT` then `BONK/USDT` on external exchanges
- Falls back to Blofin if not found

**Memecoin/New listings:**
- Newer symbols like `BOME-USDT` may not exist on major exchanges
- Automatically falls back to Blofin (limited to ~1-2 hours)

### Geo-Restrictions

If you're in a restricted location:
- OKX/Bybit may return 403 Forbidden
- Script gracefully falls back to Blofin-only mode
- Consider using a **VPN or proxy** to access external exchanges for full historical backfill

## Configuration

### Updated Parameters (.env)
```bash
BACKFILL_LOOKBACK_HOURS=168          # 7 days (only achievable with OKX/Bybit)
BACKFILL_BATCH_LIMIT=1000            # 1000 candles per request
BACKFILL_REQUEST_SLEEP_MS=200        # 200ms between API requests
BACKFILL_SYMBOL_SLEEP_MS=500         # 500ms between symbols
```

## Coverage Strategy

### 1. Live Websocket Feed (Primary)
- `blofin-stack-ingestor.service` - real-time tick ingestion
- Batched symbol subscriptions (8 symbols/batch)
- Provides continuous 1-minute resolution data

### 2. Multi-Exchange Gap Backfill (Secondary)
- `blofin-stack-gapfill.timer` - runs every 30 minutes
- **Fetches up to 7 days from OKX/Bybit** when available
- **Falls back to Blofin** for recent 1-2 hours
- Only fills actual gaps (skips existing data for efficiency)

### 3. Expected Coverage

**With OKX/Bybit access:**
- **95-99% coverage for last 7 days** (assuming ingestor has been running)
- Deep backfill possible for any new symbols added

**Without external exchange access (geo-restricted):**
- **95-99% coverage for last 24 hours** (with healthy websocket)
- Gaps older than ~2 hours cannot be backfilled
- Similar to previous behavior

**If ingestor was down:**
- With external exchanges: Can backfill up to 7 days retroactively
- Without: Gaps older than ~2 hours are permanent

## Dashboard Coverage Metrics

The dashboard (`http://127.0.0.1:8780/`) shows:
- **7-day coverage %** for each symbol
- **Missing minutes** in the rolling window
- **Data sources** used for backfill
- **Health status:**
  - `GOOD` = worst symbol ≥99.5%
  - `WARN` = worst symbol ≥97%
  - `CRITICAL` = worst symbol <97%

## Recommendations

1. **Keep `blofin-stack-ingestor.service` running continuously**  
   This is still your primary source for complete real-time data.

2. **Monitor coverage health** via the dashboard  
   Low coverage may indicate ingestor downtime or missing historical data

3. **For deep backfills**, ensure external exchange access:
   - Check if OKX/Bybit are accessible in your location
   - Use VPN/proxy if needed for initial 7-day backfill
   - Once backfilled, Blofin can maintain recent gaps

4. **For long-term storage**, consider:
   - Exporting data periodically to a separate archive
   - Using dedicated historical data providers if needed

## Troubleshooting

### "No external exchange available" warning
- All external exchanges are geo-restricted or unavailable
- Script falls back to Blofin-only mode (limited historical depth)
- Solution: Use VPN or proxy to access OKX/Bybit

### Low coverage after adding new symbols
- Run backfill manually: `python historical_backfill.py`
- With external exchange access: Should backfill 7 days
- Without: Only gets ~1-2 hours, coverage improves over time

### Specific symbol always low coverage
- May not exist on external exchanges (use Blofin only)
- Check `gap_fill_runs` table for errors
- Verify symbol format in BLOFIN_SYMBOLS config

## Files
- `ingestor.py` - Websocket → SQLite (primary real-time data)
- `historical_backfill.py` - Multi-exchange gap filler (7-day capable)
- `api_server.py` - Dashboard with coverage metrics
- `db.py` - SQLite schema (ticks table with source tracking)

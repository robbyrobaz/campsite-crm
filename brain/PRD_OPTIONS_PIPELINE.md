# PRD: IBKR Options Data Pipeline
**Status:** APPROVED — Ready to Build  
**Date:** 2026-02-28  
**Owner:** Rob  
**Builder target:** Haiku subagent via kanban  

---

## Problem

Rob wants to trade SPX 0DTE options and NQ-correlated stock options using systematic, signal-driven entries. No discretionary trades — only execute when quantitative signals say the edge is there. The pipeline must run autonomously on omen-claw and integrate with the existing IBKR paper account.

---

## Solution

A Python pipeline that:
1. Streams live SPX/NQ option chain data from IBKR
2. Computes IV skew signals continuously
3. Detects high-confidence setups (skew anomalies, term structure dislocations)
4. Logs signals to Redis (live) + DuckDB (history)
5. Eventually executes paper trades; live only with Rob's explicit approval

---

## Architecture (LOCKED)

```
IB Gateway (Docker, port 4002)
    ↓ ib_async socket
Pipeline / options_streamer.py
    ↓
Signal Engine / skew_monitor.py
    ↓              ↓
Redis (live)    DuckDB + Parquet (history)
    ↓
(Future) TradersPost / direct IBKR orders
```

**Key files:**
- `~/infrastructure/ibkr/` — all pipeline code
- `~/infrastructure/ibkr/docker/docker-compose.yml` — ib-gateway container
- `~/infrastructure/ibkr/pipeline/` — Python pipeline modules
- `~/infrastructure/ibkr/data/options.duckdb` — signal history
- `~/infrastructure/ibkr/data/skew_signals.csv` — signal log (readable by dashboard)

---

## Strategy 1: IV Skew Exploitation (BUILD FIRST)

### What it is
SPX 0DTE options consistently show elevated put-side IV vs calls (put skew) — the market prices in downside fear. When skew reaches extreme levels (>2σ above baseline), puts become overpriced. This creates a systematic edge to sell premium or buy calls.

### Signal definition
```
25Δ put IV − 25Δ call IV = skew
rolling_mean(skew, 20d) = baseline  
rolling_std(skew, 20d) = skew_std
z-score = (current_skew − baseline) / skew_std

SIGNAL when abs(z-score) > 2.0
```

### Entry rules
- `z > +2.0`: Put skew elevated → sell put spread OR buy call spread
- `z < -2.0`: Call skew elevated (rare) → sell call spread OR buy put spread
- Only trade first 90 minutes of RTH (9:30–11:00 AM ET) — highest liquidity
- Minimum open interest on each leg: 500 contracts
- Maximum position: 1 contract (paper) → 5 contracts (live, with Rob's approval)

### Exit rules
- TP: 50% of premium received
- SL: 200% of premium received (2× loss)
- Time stop: Close by 3:30 PM ET regardless
- PDT compliance: Max 3 round-trip trades per week (Rob on 25K account tier)

### Success criteria for promotion to live
- 30 paper trade sample (at least 3 weeks of trading)
- Win rate ≥ 55%
- Profit factor ≥ 1.3
- Max drawdown < 15% of notional
- No single day loss > 5% of notional

---

## Strategy 2: NQ Momentum → Options (BUILD SECOND)

### What it is
Use NQ God Model signals (already running in DRY_RUN) to trade NQ-correlated options on ETFs or futures. When the God Model fires a high-confidence directional signal, express it via defined-risk options instead of futures.

### Instruments
- QQQ options (NQ proxy, liquid, no PDT restriction on defined risk)
- MNQ options (if/when available) — smaller size
- OR SPY/SPX options on strong macro momentum

### Signal source
- `NQ-Trading-PIPELINE/smb_live_forward_test` — existing God Model output
- Only use signals with confidence > 0.7 (top 30% of signals)
- Translate: bullish NQ signal → buy QQQ call spread; bearish → buy put spread

### Why defined risk (spreads vs naked)
- Defined max loss per trade
- No margin requirements on paper
- Survives gap moves
- PDT-friendly (each spread = 1 round trip)

---

## Strategy 3: Term Structure Arbitrage (FUTURE — research only)

Not building now. IBKR 10-50ms latency is too slow for true arb. Monitor for when we have collocated data. Notes in `brain/OPTIONS_PIPELINE_RESEARCH_2026-02-28.md`.

---

## Data Requirements

### Live (available now)
- ✅ SPX index contract: `Index('SPX', 'CBOE')` qualified
- ✅ SPX option chain: expirations + strikes via `reqSecDefOptParams()`
- ✅ NQ continuous future: `ContFuture('NQ', 'CME')` = NQH6
- ✅ Historical bars: any instrument, any lookback

### Pending OPRA subscription ($1.50/month)
- ⏳ Live SPX option chain streaming (bid/ask/IV/Greeks per strike)
- ⏳ Real-time IV calculation
- Rob to enable in IBKR Client Portal → Market Data → OPRA bundle

### Smart strike filtering (avoids 100-line limit)
```python
spot = ib.reqMktData(spx)  # ~5975 currently
active_strikes = [s for s in all_strikes if abs(s - spot) / spot < 0.03]
# ±3% of spot = ~60 strikes × 2 = 120 contracts → request in batches
```

---

## Infrastructure (DONE)

| Component | Status | Location |
|-----------|--------|----------|
| IB Gateway Docker | ✅ Running | port 4002 |
| Redis | ✅ Running | port 6379 |
| ib_async venv | ✅ Installed | `~/infrastructure/ibkr/.venv` |
| DuckDB schema | ✅ Created | `data/options.duckdb` |
| Pipeline modules | ✅ Built | `pipeline/` |
| GitHub repo | ✅ Private | robbyrobaz/ibkr-pipeline |
| systemd service | ⏳ Inactive (pending OPRA) | ibkr-options.service |

**IB Gateway notes:**
- Paper trading: no 2FA required — logs in cleanly every time
- Auto-restarts at 11:59 PM nightly (IBC setting)
- `restart: "no"` in compose — won't hammer IBKR on failure
- `TWOFA_TIMEOUT_ACTION: exit` — stops instead of retrying
- Account: DUH860616 | Port: 4002 | Image: `ghcr.io/gnzsnz/ib-gateway:10.37.1o`

---

## Build Plan (Kanban Cards)

### Card 1 — Live skew monitor (build when OPRA clears)
**Title:** `Build live SPX skew monitor — stream ATM±3% strikes, compute z-score, log signals`
**project_path:** `/home/rob/infrastructure/ibkr`
**Description:** 
- Connect via ib_async to port 4002
- Request SPX option chain, filter to ATM±3% strikes
- Stream live IV via `reqMktData()` with genericTickList="106"
- Compute 25Δ put/call IV skew every minute
- Calculate rolling 20-day z-score
- When |z| > 2.0: write signal to Redis key `ibkr:skew_signal` and append to `data/skew_signals.csv`
- Log all chain snapshots to DuckDB `options_quotes` table
- Run as background thread, reconnect on disconnect

### Card 2 — Paper trade executor
**Title:** `Build paper trade executor for skew signals — iron condors / credit spreads on SPX 0DTE`
**project_path:** `/home/rob/infrastructure/ibkr`
**Description:**
- Read skew signals from Redis
- When signal fires between 9:30-11:00 AM ET:
  - Find appropriate spread legs (short 25Δ, long 15Δ)
  - Submit paper order via ib_async `placeOrder()`
  - Track position in Redis + DuckDB
  - Manage TP/SL/time stops
- Write all trades to DuckDB `paper_trades` table
- PDT guard: refuse if 3 round-trips already this week

### Card 3 — NQ signal bridge
**Title:** `Bridge NQ God Model signals to QQQ options — read smb_live_forward_test, translate to options`
**project_path:** `/home/rob/infrastructure/ibkr`
**Description:**
- Read NQ DRY_RUN signal log from `NQ-Trading-PIPELINE/`
- On high-confidence signal (>0.7): request QQQ chain
- Buy appropriate call/put spread (defined risk, 1-2 DTE)
- Log to same paper_trades table

### Card 4 — Dashboard panel
**Title:** `Add options pipeline panel to master dashboard — show live skew z-score, open trades, P&L`
**project_path:** `/home/rob/.openclaw/workspace/master-dashboard`

---

## Timeline

| Milestone | When |
|-----------|------|
| IBKR $500 clears | ~Thursday Mar 5 |
| Enable OPRA subscription | Thursday Mar 5 |
| Build Card 1 (skew monitor) | Thursday/Friday |
| 2-week paper monitoring | Mar 5–19 |
| Build Card 2 (executor) | Mar 7 (if data looks good) |
| Build Card 3 (NQ bridge) | Mar 10 |
| Evaluate live capital | Mar 19+ |

---

## Constraints / Hard Rules

- **NEVER place live orders without Rob's explicit "go live" approval**
- PDT rule: max 3 round-trip options trades per week on paper account
- No naked options — defined risk spreads only (until Rob decides otherwise)
- No market orders — limit orders only with 0.05 midpoint slack
- No trading last 30 min of RTH (3:30–4:00 PM ET) — liquidity drops sharply
- NQ live trading hard rule still applies: DRY_RUN=True on all NQ futures

---

## Connection to NQ Pipeline

The NQ pipeline (`NQ-Trading-PIPELINE/`) and options pipeline share:
- Same IBKR connection (different clientId — NQ uses clientId=1, options uses clientId=10+)
- Same omen-claw server
- NQ signals feed into options Strategy 2 (NQ momentum → QQQ options)
- Both monitored by HEARTBEAT.md oversight cron
- Both visible on master dashboard

**NQ data via IBKR (bonus):** Now that ib-gateway is running, NQ historical data is available as a backup source alongside the primary SMB watcher. Don't switch — SMB is the live feed. IBKR is a redundancy/research source.

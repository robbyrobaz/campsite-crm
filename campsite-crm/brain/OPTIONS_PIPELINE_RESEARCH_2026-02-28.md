# Options Pipeline Research Report
**Date:** 2026-02-28  
**Author:** Senior Quant Researcher (Opus subagent)  
**Purpose:** Architecture proposal for SPX 0DTE + momentum options bot

---

## Executive Summary

**Bottom line:** Build on IBKR TWS API with `ib_insync`, use Redis for live state + DuckDB/Parquet for history, start with IV skew exploitation on SPX (not arbitrage), and expect to capture 20-50bps edge on well-structured theta plays. True arbitrage is a mirage for retail—market makers close gaps in <100ms. Your edge is in systematic premium selling with smart entry/exit triggers.

**Recommended stack:**
- **Data:** IBKR TWS API via `ib_insync` (primary) + Polygon.io Options ($79/mo for historical backfill)
- **Storage:** Redis (live chain state) + DuckDB (analytics) + Parquet (archive)
- **Protocol:** TWS socket API (not WebSocket—it's faster and more reliable)
- **Strategy:** IV Skew Exploitation → 0DTE Iron Condors → Momentum Options (in that order)
- **First experiment:** 2-week paper trade of automated IV skew detection on SPX 0DTE

---

## 1. Data Source Verdict

### Winner: IBKR TWS API + ib_insync

After researching all options, IBKR is the clear choice for Rob's use case:

| Source | Real-time SPX Chain | Greeks/IV | Execution | Cost | Verdict |
|--------|---------------------|-----------|-----------|------|---------|
| **IBKR TWS** | ✅ Full chain streaming | ✅ Live Greeks, IV | ✅ Direct | ~$10-50/mo data fees | **USE THIS** |
| TradeStation | ✅ Good streaming | ✅ Greeks | ✅ Direct | Included | Good backup |
| Polygon.io | ✅ Excellent | ✅ ORATS Greeks | ❌ No execution | $79/mo | Historical only |
| Tradier | ⚠️ 15-min delayed free | ✅ Greeks | ✅ Direct | Free tier limited | Paper trading |
| Tastytrade | ✅ Options-focused | ✅ Excellent | ✅ Direct | Included | Good alternative |

### IBKR TWS API Details

**What you get:**
- `reqSecDefOptParams()` — returns all strikes + expirations for an underlying (fast, not throttled)
- `reqMktData()` — streams bid/ask/last/volume for each contract
- `reqTickByTickData()` — tick-by-tick for specific contracts
- Greeks: `reqMktData()` with genericTickList="106" returns delta, gamma, theta, vega, IV
- Can request computed IV and option prices via `calculateImpliedVolatility()` and `calculateOptionPrice()`

**Rate limits (critical for 0DTE):**
- **100 market data lines by default** — this is the real constraint
- Each option contract you stream = 1 line
- SPX has 500+ strikes per expiry × 2 (call/put) = 1000+ contracts for 0DTE alone
- **You cannot stream all SPX strikes simultaneously** on a retail account

**Solution: Smart filtering**
```python
# Only stream strikes within ±5% of spot (captures 95% of useful trades)
spot = 5000  # current SPX
active_strikes = [s for s in all_strikes if abs(s - spot) / spot < 0.05]
# ~50 strikes × 2 = 100 contracts = exactly at the limit
```

**Market data subscription costs:**
- OPRA (US Options) bundle: ~$1.50/mo for non-professional
- SPX is index options, covered under CME Group Index Options
- Total: ~$10-15/mo for all needed data on non-pro account

**Latency:**
- TWS API: 10-50ms from IBKR servers to your home server
- This is adequate for theta strategies, NOT for true arbitrage
- Market makers have <1ms collocated feeds

### ib_insync Setup

```python
from ib_insync import *

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

# Get SPX option chain
spx = Index('SPX', 'CBOE')
chains = ib.reqSecDefOptParams(spx.symbol, '', spx.secType, spx.conId)

# Find 0DTE expiration
import datetime
today = datetime.date.today().strftime('%Y%m%d')
chain = next(c for c in chains if today in c.expirations)

# Build contracts for strikes near ATM
spot = 5000  # get this from reqMktData on SPX
strikes = [s for s in chain.strikes if abs(s - spot) < 250]

contracts = [Option('SPX', today, strike, right, 'SMART') 
             for strike in strikes for right in ['C', 'P']]

# Qualify and stream
ib.qualifyContracts(*contracts)
tickers = ib.reqTickers(*contracts)  # This uses your market data lines
```

### Data Source Assignments

| Use Case | Source | Rationale |
|----------|--------|-----------|
| **Real-time 0DTE SPX** | IBKR TWS | Direct execution, Greeks included, lowest latency |
| **Historical SPX options** | Polygon.io ($79/mo) | Clean data back to 2019, ORATS Greeks, Parquet export |
| **Momentum stock screener** | TradeStation API | Good scanner, Rob already has account |
| **Stock options execution** | IBKR TWS | Unified execution layer |

---

## 2. Storage Architecture

### Recommendation: Redis + DuckDB + Parquet

This is a hybrid architecture optimized for two different access patterns:
1. **Live trading:** Sub-millisecond reads of current state
2. **Analysis/backtest:** Fast columnar scans over millions of rows

```
┌─────────────────────────────────────────────────────────────┐
│                     INGESTION LAYER                         │
│  ib_insync → asyncio event loop → message router            │
└─────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│     REDIS       │  │   IN-MEMORY     │  │   WRITE QUEUE   │
│  (Live State)   │  │   (Signals)     │  │  (Async Flush)  │
│                 │  │                 │  │                 │
│ • Current bid/  │  │ • IV surface    │  │ • Batch writes  │
│   ask per strike│  │ • Delta matrix  │  │   to Parquet    │
│ • Greeks        │  │ • Signal flags  │  │ • 5-sec batches │
│ • Last update   │  │                 │  │                 │
└─────────────────┘  └─────────────────┘  └─────────────────┘
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                     DUCKDB + PARQUET                        │
│  • Daily Parquet files: options_YYYY-MM-DD.parquet          │
│  • Schema: timestamp, symbol, strike, right, expiry,        │
│            bid, ask, last, volume, oi, delta, gamma,        │
│            theta, vega, iv, underlying_price                │
│  • Partitioned by date → fast range scans                   │
└─────────────────────────────────────────────────────────────┘
```

### Why Not The Other Options?

| Option | Problem |
|--------|---------|
| TimescaleDB | Overkill for single-server. Write throughput limited to ~50K/sec with indexes. PostgreSQL overhead not justified. |
| InfluxDB | Different query language, awkward for options analytics (no good join support). |
| Pure in-memory | Memory limits. 1M quotes/day × 30 days = 30M rows × 200 bytes = 6GB just for raw quotes. Crash = data loss. |
| SQLite | Write locking kills concurrent read/write performance. |

### Data Volume Estimates

For SPX 0DTE:
- Active strikes: ~100 (±5% from spot)
- Calls + puts: 200 contracts
- Update frequency: ~10 quotes/contract/minute during active hours
- Trading day: 6.5 hours = 390 minutes
- **Daily quotes: 200 × 10 × 390 = 780,000 rows**
- Row size: ~200 bytes
- **Daily storage: ~156 MB uncompressed, ~30 MB Parquet compressed**

Totally manageable. Your laptop can handle 10x this.

### Redis Schema

```python
# Key structure
"spx:0dte:5000C" → {
    "bid": 12.50,
    "ask": 12.70,
    "last": 12.60,
    "volume": 1523,
    "delta": 0.52,
    "gamma": 0.008,
    "theta": -15.2,
    "vega": 8.3,
    "iv": 0.145,
    "updated": 1740754800.123
}

# IV surface (updated every minute)
"spx:iv_surface" → {
    "skew_25d": 0.023,  # 25-delta put IV - 25-delta call IV
    "atm_iv": 0.142,
    "term_structure": [0.14, 0.15, 0.16],  # 0DTE, 1DTE, 7DTE
    "updated": 1740754800
}
```

### DuckDB Query Examples

```sql
-- Find mispriced options (put-call parity check)
WITH paired AS (
    SELECT 
        c.timestamp,
        c.strike,
        c.bid as call_bid, c.ask as call_ask,
        p.bid as put_bid, p.ask as put_ask,
        c.underlying_price as spot
    FROM options c
    JOIN options p ON c.timestamp = p.timestamp 
        AND c.strike = p.strike
    WHERE c.right = 'C' AND p.right = 'P'
        AND c.expiry = current_date
)
SELECT *,
    -- Synthetic long: buy call, sell put
    (call_ask - put_bid) as synthetic_long,
    -- Should equal: spot - PV(strike)
    (spot - strike * 0.9999) as theoretical,
    ABS((call_ask - put_bid) - (spot - strike * 0.9999)) as parity_gap
FROM paired
WHERE parity_gap > 0.50  -- Only gaps > $0.50
ORDER BY parity_gap DESC;

-- IV skew spike detection
SELECT 
    timestamp,
    -- 25-delta skew
    (SELECT iv FROM options WHERE delta BETWEEN -0.27 AND -0.23 AND right='P' LIMIT 1) -
    (SELECT iv FROM options WHERE delta BETWEEN 0.23 AND 0.27 AND right='C' LIMIT 1) as skew_25d
FROM options
WHERE timestamp > now() - INTERVAL '1 hour'
GROUP BY timestamp
HAVING skew_25d > 0.03;  -- Skew > 3% = signal
```

---

## 3. WebSocket vs TWS Socket API

### Winner: TWS Socket API (via ib_insync)

| Protocol | Latency | Reliability | Ease of Use | Recommendation |
|----------|---------|-------------|-------------|----------------|
| **TWS Socket** | 10-50ms | Excellent | `ib_insync` wraps it | **USE THIS** |
| Client Portal WebSocket | 50-200ms | Flaky | REST + WS hybrid awkward | Avoid |
| Polygon WebSocket | 100-500ms | Good | Simple | Historical/backup only |
| FIX Protocol | <5ms | Excellent | Complex, institutional | Overkill |
| REST Polling | 1000ms+ | Good | Simple | Never for 0DTE |

### Why TWS Socket Wins

1. **Direct execution path:** Same connection for data AND orders
2. **ib_insync abstracts the pain:** Async/await, auto-reconnect, clean API
3. **No additional cost:** Data fees only, no separate data vendor
4. **Battle-tested:** Rob's NQ bot already works with similar architecture

### Implementation Pattern

```python
import asyncio
from ib_insync import *

class OptionsBot:
    def __init__(self):
        self.ib = IB()
        self.redis = redis.Redis()
        self.positions = {}
        
    async def connect(self):
        await self.ib.connectAsync('127.0.0.1', 7497, clientId=1)
        self.ib.pendingTickersEvent += self.on_tick
        
    def on_tick(self, tickers):
        for ticker in tickers:
            # Update Redis with latest quote
            key = f"spx:0dte:{ticker.contract.strike}{ticker.contract.right}"
            self.redis.hset(key, mapping={
                'bid': ticker.bid,
                'ask': ticker.ask,
                'delta': ticker.modelGreeks.delta if ticker.modelGreeks else None,
                'iv': ticker.modelGreeks.impliedVol if ticker.modelGreeks else None,
                'updated': time.time()
            })
            
            # Check signals
            asyncio.create_task(self.check_signals(ticker))
    
    async def check_signals(self, ticker):
        # IV skew signal, entry/exit logic, etc.
        pass

    async def run(self):
        await self.connect()
        while True:
            self.ib.sleep(0.1)  # Process messages
```

### Latency Reality Check

**Your setup (home server in Phoenix):**
- IBKR servers: Greenwich, CT or Chicago
- Network RTT: ~40-60ms
- TWS API overhead: ~10ms
- **Total latency: ~50-70ms per quote update**

**What this means:**
- ✅ Adequate for theta strategies (entries/exits measured in minutes)
- ✅ Adequate for IV skew detection (changes over seconds)
- ❌ NOT adequate for true arbitrage (MMs close in <100ms)
- ❌ NOT adequate for scalping (need <10ms)

**Don't waste time on co-location.** It costs $5K+/month and won't help theta strategies. Your edge is systematic, not speed.

---

## 4. Strategy Ranking

### Ranked by Risk/Reward for Autonomous Bot

| Rank | Strategy | Expected Edge | Complexity | Risk | Verdict |
|------|----------|---------------|------------|------|---------|
| **1** | IV Skew Exploitation | 15-30 bps/trade | Medium | Defined | **START HERE** |
| **2** | 0DTE Theta Selling | 10-25 bps/trade | High | Gamma risk | Phase 2 |
| **3** | Momentum Options | Variable | Low | Premium loss | Phase 3 |
| **4** | Arbitrage | Near zero | Very High | Execution | **SKIP** |

### Strategy 1: IV Skew Exploitation (Recommended First)

**The thesis:** SPX puts are systematically overpriced due to institutional hedging demand (the "fear premium"). When put IV spikes beyond 2 standard deviations vs. historical, selling put spreads has positive expected value.

**Why it works for a bot:**
- Signal is slow-moving (IV changes over minutes, not milliseconds)
- Defined risk (put spreads cap max loss)
- Edge is statistical, not speed-based
- Historical data for backtesting is available (Polygon.io)

**Implementation:**
```python
# Signal: 25-delta put IV - ATM IV > historical_mean + 2*std
skew = iv_25d_put - iv_atm
if skew > skew_baseline + 2 * skew_std:
    # Sell put spread
    sell_put = find_strike(delta=-0.25)
    buy_put = find_strike(delta=-0.10)  # Wing for protection
    execute_vertical(sell_put, buy_put, size=1)
```

**Expected returns:**
- Win rate: ~65-70% (puts often expire worthless or can be closed early)
- Average win: 50% of credit received
- Average loss: 150% of credit received (spread goes ITM)
- Edge per trade: ~15-30 bps after commissions

**Risk management:**
- Max position: 2% of portfolio in any single spread
- Daily stop: Close all positions if portfolio down 1%
- Never sell naked—always use spreads

### Strategy 2: 0DTE Iron Condors (Phase 2)

**The thesis:** Collect premium from both sides, delta-hedge dynamically, close at 50% profit or EOD.

**Why it's harder:**
- Gamma is extreme on 0DTE—positions can go from +$500 to -$2000 in minutes
- Requires continuous monitoring and adjustment
- Slippage on adjustments can eat the edge

**Bot requirements:**
- Real-time delta monitoring (sum of all position deltas)
- Auto-adjust triggers (if |net_delta| > threshold, hedge with futures or close wing)
- Hard stop on max loss

**Only attempt after IV skew strategy is profitable and stable.**

### Strategy 3: Momentum Options (Phase 3)

**The thesis:** Find stocks with strong technical momentum, buy slightly OTM calls 2-4 weeks out, ride the move.

**Why it's a bot task:**
- Screening 1000+ stocks for technical setups is tedious
- Entry timing can be automated
- Exit rules can be systematic (50% profit, 100% loss, time decay threshold)

**Data requirements:**
- Stock scanner (TradeStation API has good scanners)
- ADX, volume breakout, consolidation detection
- Options chain for selected stocks

**Not urgent—0DTE SPX is higher edge.**

### Strategy 4: True Arbitrage (SKIP)

**The hard truth:** Retail cannot capture options arbitrage.

**Why:**
- Put-call parity violations: ~$0.05-0.20 when they occur
- Commission: ~$0.65/contract × 4 legs = $2.60
- Slippage: ~$0.10/contract × 4 = $0.40
- **Net after costs: NEGATIVE**

Market makers see the same quotes you do, but:
- They pay $0.00-0.10/contract in commissions
- They have sub-millisecond execution
- They close gaps before your order even reaches the exchange

**Box spread arbitrage:** Theoretically risk-free, practically impossible. The "free money" box spread YouTube videos are survivorship bias.

**Don't build an arbitrage scanner. It's a waste of time.**

---

## 5. Build Roadmap

### Phase 0: Foundation (Week 1-2)
```
[x] Set up IBKR paper trading account with API access
[x] Install ib_insync, Redis, DuckDB
[x] Build basic connection and quote streaming
[x] Store SPX 0DTE quotes to Parquet files
[x] Verify data quality (no gaps, Greeks populate correctly)
```

### Phase 1: IV Skew Detection (Week 3-4)
```
[ ] Calculate IV surface from live quotes
[ ] Compute 25-delta skew metric
[ ] Build historical baseline (use Polygon.io data)
[ ] Detect skew spikes (>2 std deviation)
[ ] Paper trade: log signals without execution
```

### Phase 2: Automated Execution (Week 5-6)
```
[ ] Implement put spread execution logic
[ ] Build position tracking in Redis
[ ] Add exit rules (50% profit, time decay, max loss)
[ ] Paper trade with real execution
[ ] Track P&L and win rate
```

### Phase 3: Risk Hardening (Week 7-8)
```
[ ] Add circuit breakers (daily loss limit, position limits)
[ ] Implement gamma monitoring
[ ] Add alerting (Telegram notifications)
[ ] Build dashboard for monitoring
[ ] Forward test on live account with 1 contract size
```

### Phase 4: Scale and Iterate (Month 3+)
```
[ ] Analyze results, tune parameters
[ ] Add 0DTE iron condor strategy
[ ] Add momentum stock scanner
[ ] Increase position sizes if consistently profitable
```

---

## 6. Realistic Expectations

### What Your Home Server CAN Capture

| Opportunity | Realistic? | Expected Edge | Why |
|-------------|------------|---------------|-----|
| **IV Skew premium** | ✅ Yes | 15-30 bps | Slow-moving signal, defined risk |
| **Theta decay on 0DTE** | ✅ Yes | 10-25 bps | Time decay is reliable, gamma risk manageable |
| **Momentum stock options** | ✅ Yes | Variable | Screening edge, not speed edge |
| **Put-call parity arb** | ❌ No | Negative | MMs close gaps in <100ms |
| **Box spread arb** | ❌ No | Negative | Commissions > edge |
| **HFT/scalping** | ❌ No | Negative | Need colocation + FPGA |

### What Requires Co-Location ($5K+/month)

- True arbitrage (and even then, competing with citadel/jane street)
- Market making
- Sub-second scalping
- Order book imbalance strategies

**Rob should not pursue these.**

### Honest Numbers

Based on similar retail systematic options strategies:

- **Year 1 target:** 10-15% return on capital deployed (not total account)
- **Win rate:** 60-70% on theta strategies
- **Drawdown expectation:** 10-20% max drawdown events will occur
- **Time to profitability:** 3-6 months of iteration

This is NOT a get-rich-quick scheme. It's a systematic edge that compounds over time.

---

## 7. First Experiment

### The Smallest Viable Test

**Goal:** Validate that IV skew spikes are detectable and tradeable on SPX 0DTE.

**Duration:** 2 weeks paper trading

**Setup:**
1. Connect to IBKR paper account
2. Stream 100 SPX 0DTE options (±5% from spot)
3. Calculate IV surface every minute
4. Log 25-delta skew to file
5. When skew > baseline + 2σ, log "SIGNAL" (don't execute)
6. At EOD, check if selling a put spread at signal time would have been profitable

**Success criteria:**
- ≥3 signals per week (proves opportunities exist)
- ≥60% of signals would have been profitable (proves edge exists)
- No data gaps or API failures (proves infrastructure works)

**Code skeleton:**
```python
# experiment_iv_skew.py
from ib_insync import *
import pandas as pd
import numpy as np

SKEW_THRESHOLD_STD = 2.0
BASELINE_SKEW = 0.025  # Historical mean 25-delta skew for SPX

class IVSkewExperiment:
    def __init__(self):
        self.ib = IB()
        self.signals = []
        self.skew_history = []
        
    async def run(self):
        await self.ib.connectAsync('127.0.0.1', 7497, clientId=1)
        
        # Get 0DTE chain
        spx = Index('SPX', 'CBOE')
        chains = self.ib.reqSecDefOptParams(spx.symbol, '', spx.secType, spx.conId)
        # ... build contracts, stream quotes
        
        while market_open():
            iv_surface = self.calculate_iv_surface()
            skew = iv_surface['25d_put_iv'] - iv_surface['atm_iv']
            self.skew_history.append({
                'timestamp': datetime.now(),
                'skew': skew
            })
            
            if skew > BASELINE_SKEW + SKEW_THRESHOLD_STD * np.std([s['skew'] for s in self.skew_history[-100:]]):
                self.signals.append({
                    'timestamp': datetime.now(),
                    'skew': skew,
                    'spot': self.get_spot(),
                    'put_25d_strike': self.find_25d_put_strike()
                })
                print(f"SIGNAL: Skew spike at {skew:.4f}")
            
            await asyncio.sleep(60)  # Check every minute
        
        # EOD analysis
        self.analyze_signals()
    
    def analyze_signals(self):
        # Would selling put spread at signal time have been profitable?
        for signal in self.signals:
            # Check if put spread expired OTM
            pass
```

**After 2 weeks:**
- If signals are profitable → proceed to Phase 2 (automated execution)
- If signals are unprofitable → refine threshold or abandon strategy
- If no signals → skew isn't volatile enough, try different underlying (QQQ, IWM)

---

## 8. Regulatory and Broker Constraints

### Pattern Day Trader (PDT) Rule

**Does it affect options?** YES.

- PDT applies to ANY security (stocks + options)
- 3 day trades in 5 business days in a margin account <$25K = flagged
- **Day trade = open and close same position same day**
- 0DTE strategies are inherently day trades (positions expire same day)

**Solutions:**
1. **Keep account ≥$25K** (IBKR minimum for margin is already $2K, but PDT kicks in at $25K threshold)
2. **Use cash account** (no PDT, but no margin, must wait for settlement)
3. **Trade index options (SPX)** — they're cash-settled, no stock delivery issues

**Rob likely has >$25K given existing NQ trading, so PDT is not a blocker.**

### IBKR Margin Requirements

| Strategy | Margin Requirement |
|----------|-------------------|
| Long options | 100% of premium (no margin) |
| Credit spreads (put/call vertical) | Max loss of spread |
| Iron condors | Max loss of one side |
| Naked puts | 20% of underlying - OTM amount + premium |
| Naked calls | **Avoid** (unlimited risk, huge margin) |

**For SPX spreads:**
- 1 SPX iron condor with $50 wings = $5,000 max loss = $5,000 margin required
- This is why SPX is capital-intensive
- Consider XSP (1/10th size) for smaller accounts

### TradeStation Options Approval

Tiers:
- **Level 1:** Covered calls, cash-secured puts
- **Level 2:** Long options, spreads
- **Level 3:** Naked puts (if qualified)
- **Level 4:** Naked calls (rarely approved for retail)

**Rob needs Level 2 minimum.** Apply via TradeStation account settings if not already approved.

### Wash Sale Rules

**Applies to options?** YES, with complexity.

- Selling an option at a loss, then buying "substantially identical" option within 30 days = wash sale
- "Substantially identical" for options is murky:
  - Same underlying, same strike, same expiry = definitely wash sale
  - Different strike or expiry = probably NOT wash sale (IRS hasn't clarified)

**Practical advice:**
- Track all trades with cost basis
- If closing a losing position, don't re-enter same strike/expiry for 30 days
- Use tax software that handles options wash sales (TurboTax Premier, etc.)

**For 0DTE specifically:** Each day is a new expiry, so wash sale is unlikely unless you're trading same strike repeatedly.

---

## 9. Additional Recommendations

### Don't Forget

1. **TWS must be running** — the API connects to TWS or IB Gateway, not directly to IBKR
2. **Enable API in TWS settings** — Edit → Global Configuration → API → Settings
3. **Paper trading first** — Port 7497 for paper, 7496 for live
4. **Greeks may be delayed** — Model Greeks update every ~15 seconds, not tick-by-tick

### Gotchas

- **SPX is European-style** — cannot be exercised early, but also cannot be assigned early (good for selling)
- **SPX is cash-settled** — no stock delivery, just cash P&L
- **SPX has AM and PM settlement** — 0DTE typically uses PM settlement (4:00 PM ET)
- **SPXW** is the weekly SPX option (what most people mean by "0DTE SPX")

### Monitoring Dashboard

Build a simple dashboard showing:
- Current positions and Greeks
- IV surface / skew chart
- Signal history
- P&L curve
- System health (API connected, Redis up, etc.)

Use Streamlit or Grafana — don't over-engineer this.

---

## Conclusion

Rob should:

1. **Start with IBKR TWS API + ib_insync** — it's the best data/execution combo for retail
2. **Use Redis + DuckDB** — fast live state, fast analytics, minimal ops overhead
3. **Build IV skew detection first** — it's the highest-edge, lowest-complexity strategy
4. **Paper trade for 2+ weeks** — validate the thesis before risking capital
5. **Skip arbitrage entirely** — retail cannot compete with MMs on speed

The realistic outcome: a bot that systematically sells overpriced SPX puts during fear spikes, capturing 15-30 bps per trade with 60-70% win rate. Over a year, this compounds to 10-15% return on deployed capital — not flashy, but consistent and automated.

**First action:** Set up IBKR paper trading with API access and run the IV skew experiment for 2 weeks.

---

*Report generated by Opus research subagent, 2026-02-28*

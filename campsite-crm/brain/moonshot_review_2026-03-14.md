# Moonshot v2 Review — March 14, 2026

## Executive Summary

**Verdict: Fix, don't rebuild.** The system architecture is sound, but has 5 critical issues blocking profitability. A rebuild would take 2+ weeks and we'd lose the 95 cycles of data already collected. Fix the bugs, tune the gates, and let the tournament run.

---

## What's Working ✅

1. **Infrastructure is solid**
   - 95 cycles completed, 470 coins tracked, 918K candles stored
   - 5.2GB DB running clean, no corruption
   - Dashboard live on 8893, all timers firing
   - 3.5M labels generated (13% positive rate — reasonable for 15%/5% targets)

2. **Tournament is functioning**
   - 968 models generated, 801 retired, 156 in FT, 10 in backtest
   - Backtest gate is working (rejecting ~95% of challengers)
   - 22K positions opened/closed (real trading volume)
   - Champion model exists (`de44f72dbb01`, short, CatBoost, FT PF 2.22)

3. **Data pipeline is complete**
   - All 50 features implemented and computing
   - Social signals collecting (Fear & Greed, trending, news, Reddit, GitHub)
   - Extended market data (funding, OI, mark prices, tickers) working

---

## What's Broken 🔴

### 1. **LONG DIRECTION IS DEAD** (Critical)
- **No long champion promoted** — only 1 short champion exists
- Long models: 474 generated, but none passed FT promotion
- Likely causes:
  - Label generation bug for long direction (inverted logic?)
  - Long TP/SL asymmetry (market dumps faster than it pumps in crypto)
  - Backtest using short-biased data (crypto bear trend in training window)

**Fix:** 
- Verify `labels/generate.py` long label logic (path-dependent check)
- Run spot check: pick 5 coins that hit +15% in last 30 days, verify labels=1
- If labels are correct, accept that crypto IS short-biased and focus on short models only
- Alternative: lower long TP to 10% (asymmetric R:R for asymmetric market)

---

### 2. **WIN RATE IS TERRIBLE** (17.5%, avg PnL -0.7%)
- 21,850 closed positions, only 3,816 wins
- Current champion: FT PF 2.22, but **avg PnL negative** across all positions
- This suggests: **leverage is magnifying losses more than wins**

**Diagnosis:**
- TP_PCT = 0.15, SL_PCT = 0.05 (3:1 R:R)
- LEVERAGE = 3x → effective 45%/15% PnL targets
- With leverage, SL hits are **catastrophic** (-15% real vs -5% unleveraged)
- Slippage + volatility means SL hits at worse prices → -20% to -30% realized losses

**Fix:**
- **Remove leverage entirely for now** (`LEVERAGE=1`)
- Re-run last 500 closed positions with 1x leverage math — does WR improve?
- If WR stays low, the models are just bad — tournament needs more time
- If WR improves to 25-30%, it's a position sizing problem, not a signal problem

---

### 3. **MEMORY KILLS MID-CYCLE** (Blocking progress)
- Last cycle (Mar 14 04:16) killed with status=9 (SIGKILL, likely OOM)
- Cycle was running backtest fold 2 when killed (30min+ into 7min backtest)
- 22GB RAM available, but backtests load 3.5M labels + 900K candles into memory

**Diagnosis:**
- Backtest loads entire label set (1.7M rows per direction) into pandas DataFrame
- 3 folds × 2 directions × full feature matrix = 10GB+ transient RAM usage
- When combined with existing open positions + features, hits OOM

**Fix:**
- Batch backtest: load labels in 100K chunks, score incrementally
- OR: Use DuckDB for backtest (query labels on-disk, never load to RAM)
- OR: Reduce `MIN_BT_TRADES` from 50 to 30 (smaller test sets)
- Short-term: increase systemd `MemoryMax=` to 16GB to prevent OOM kill

---

### 4. **FEATURE INVALIDATION WARNINGS FLOODING LOGS**
```
WARNING moonshot _load_model_for_invalidation: bad feature_set JSON for a93fdc381592
```
- Hundreds of these warnings every cycle
- Means: old FT models have malformed `feature_set` stored in DB
- Consequence: INVALIDATION exit can't re-score positions → positions held longer than intended → drawdown

**Fix:**
- Run migration: `UPDATE tournament_models SET feature_set = '[]' WHERE feature_set IS NULL OR feature_set = ''`
- Add validation: when storing model, verify `json.loads(feature_set)` succeeds
- Log once per model, not once per position (reduce log spam)

---

### 5. **BACKTEST GATE TOO STRICT OR LABELS WRONG**
- 95% of challengers fail backtest (801 retired / 968 total)
- Current gates: `MIN_BT_PF=1.0`, `MIN_BT_PRECISION=0.20`
- Avg backtest result: PF 0.5-1.0, precision 0.15-0.25

**Two possibilities:**
1. **Labels are wrong** — path-dependent logic inverted or broken
2. **Market is just hard** — 15%/5% targets on 4h timeframe are tough

**Diagnosis test:**
- Query top 10 label=1 examples from `labels` table
- Pull their candles, manually verify: did price hit +15% before -5%?
- If labels are correct → market is hard, gates are fine
- If labels are wrong → fix label generation, regenerate all labels

**If labels are correct:**
- Accept 95% rejection rate — tournament is working as designed
- Lower `MIN_BT_PF` to 0.8 → more models reach FT → more FT data
- Focus on FT performance, not BT gates

---

## Performance Analysis

### Champion Model (`de44f72dbb01`, short)
- **FT Performance:** 388 trades, FT PnL +68%, FT PF 2.22
- **BT Performance:** PF 0.98 (FAILED backtest, but promoted anyway?)
- **Issue:** BT PF < 1.0 means model lost money in backtest, but won in FT
  - Either: backtest overfits to old data, FT captures new regime
  - Or: bug in promotion logic (champion shouldn't have PF 0.98 in BT)

### Recent Closed Trades
| Symbol | Direction | PnL | Exit Reason |
|--------|-----------|-----|-------------|
| GWEI-USDT | short | +54% | TAKE_PROFIT ✅ |
| EDEN-USDT | short | -20% | STOP_LOSS |
| TOWNS-USDT | short | -73% | STOP_LOSS (leverage disaster) |
| CL-USDT | short | -23% | STOP_LOSS |
| C98-USDT | short | -29% | STOP_LOSS |

**Pattern:** 1 big winner, 4 SL hits. This is expected with 17.5% WR, but the -73% loss is NOT — that's a 3x leveraged -24% move, which should have hit SL at -15% (5% × 3x).

**Bug?** SL may not be firing correctly, or slippage is extreme on illiquid coins.

---

## Data Quality

### Candle Coverage
- 470 coins, 918K candles (avg 1,950 bars per coin)
- Oldest candle: July 2024 (~20 months)
- Good coverage for 4h backtest (need ~6 months minimum)

### Label Distribution
- Long: 1.76M samples, 13.2% positive (231K wins)
- Short: 1.77M samples, 13.4% positive (236K wins)
- **Balanced** — no obvious label generation bias

### Social Signals
- Fear & Greed: working (last: score=16, 7d change=+4)
- Trending coins: working (CoinGecko API live)
- News/Reddit: collecting but **zero mentions** in recent features
  - Either: feature extraction broken, or coins in positions don't get news coverage
  - Not critical (models can ignore zero-value features)

---

## Tournament Health

### Model Lifecycle
- **Backtest:** 10 active (being evaluated now)
- **Forward Test:** 156 models (WAY over `MAX_FT_MODELS=10` setting)
  - Bug: demotion logic not firing, or `MIN_FT_TRADES_EVAL=500` too high
  - Most FT models have 25-400 trades (not hitting 500 eval threshold)
- **Retired:** 801 models (normal attrition)
- **Champion:** 1 (should be 2 — long + short)

**Fix demotion:**
- Lower `MIN_FT_TRADES_EVAL` from 500 → 100
- Run manual sweep: demote FT models with `ft_trades > 100 AND ft_pf < 0.8`
- Free up FT slots for new challengers

---

## Rebuild vs Fix Decision Matrix

| Factor | Rebuild | Fix | Winner |
|--------|---------|-----|--------|
| **Time to production** | 2-4 weeks | 3-5 days | Fix |
| **Risk** | High (new bugs) | Low (isolated changes) | Fix |
| **Data preservation** | Lose 95 cycles | Keep all data | Fix |
| **Architecture soundness** | Same design | Same design | Tie |
| **Agent team coordination** | Complex (5 agents) | Simple (you + 1 builder) | Fix |

**Conclusion:** The PRD is good. The architecture is good. The bugs are fixable. Don't rebuild.

---

## Recommended Fix Plan (5 days)

### Day 1: Diagnosis (no code changes)
1. Verify long labels are correct (manual spot check on 10 coins)
2. Verify SL is firing at correct price (check recent -73% loss)
3. Measure backtest memory usage (add logging, run 1 cycle)
4. Query: why are 156 FT models not being demoted?

### Day 2: Critical Fixes
1. **Remove leverage** (`LEVERAGE=1` in config)
2. **Fix feature_set JSON** (migration + validation)
3. **Batch backtest** (chunk labels in 100K batches)
4. **Lower FT eval threshold** (`MIN_FT_TRADES_EVAL=100`)

### Day 3: Long Direction
1. If long labels are wrong → fix `labels/generate.py`, regenerate
2. If long labels are correct but no winners → lower `TP_PCT` for long only (asymmetric)
3. Alternative: disable long entirely, focus on short-only system

### Day 4: Demotion + Slot Management
1. Manual sweep: retire FT models with PF < 0.8 after 100+ trades
2. Verify `MAX_FT_MODELS=10` enforced (currently 156 active)
3. Add circuit breaker: pause model if DD > 50%

### Day 5: Validation
1. Run 3 full cycles (12 hours) — verify no OOM kills
2. Check: new champions promoted? Long direction working?
3. Analyze: WR with 1x leverage vs 3x leverage on last 500 trades
4. Decision: re-enable leverage at 2x if WR > 25%, else stay at 1x

---

## What NOT to Change

1. **Don't rebuild from scratch** — architecture is fine
2. **Don't change TP/SL drastically** — 15%/5% is reasonable for moonshots
3. **Don't add external data** — Blofin-native is working, social is bonus
4. **Don't pause the system** — every cycle = more FT data
5. **Don't spawn Agent Teams** — this is 1-2 builder cards max

---

## Success Metrics (30 days from fixes)

| Metric | Current | Target |
|--------|---------|--------|
| **Long champion exists** | No | Yes |
| **FT models active** | 156 | 10-15 |
| **Avg WR (1x leverage)** | 17.5% | 25%+ |
| **Champion FT PF** | 2.22 | 2.5+ |
| **Cycles without OOM** | 0/last 3 | 20/20 |
| **Avg FT PnL (top 5)** | +0.3 | +1.0 |

If we hit these in 30 days → allocate $5K real capital for live test.
If we don't → revisit PRD assumptions (maybe 30% targets are too aggressive).

---

## Bottom Line

**Don't rebuild. Fix the 5 bugs, run 20 more cycles, reassess.**

The tournament IS working — 968 models tested, 1 champion promoted, 22K trades executed. The problem is leverage + a few fixable bugs, not the core design.

Agent Teams would take 2 weeks and give us the same architecture with different bugs. Better to fix known bugs than introduce unknown ones.

**Next step:** Create 5 kanban cards (1 per bug), dispatch them, verify fixes in 5 days.

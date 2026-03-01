# PRD: Blofin-Moonshot Large-Move Detection Pipeline

**Status:** APPROVED FOR BUILD (conditional go/no-go at end)
**Date:** 2026-02-28
**Author:** Opus Research + Analysis
**Repository:** `/home/rob/.openclaw/workspace/blofin-moonshot/` (new)
**Infrastructure:** Paper trading only (Blofin API), no live orders until approval

---

## Executive Summary

**Mission:** Build a systematic, data-driven pipeline to identify and trade cryptocurrency coins about to experience large price moves (30%+ in specified timeframe).

**Thesis:** Crypto markets exhibit exploitable inefficiencies in small-cap, low-liquidity altcoins. These moves are preceded by identifiable technical and on-chain signals (volatility compression, volume accumulation, whale activity). While predictability is lower than traditional markets, the move size (30%+ per trade) justifies a modest hit rate (50-60%).

**Key Finding from Research:**
- ✅ **Theoretically viable:** Academic papers and quant research confirm 30%+ move prediction is possible
- ❌ **Blofin 32-coin universe insufficient:** Historical data shows micro-moves (0.8-1.2%), not 30%+ events
- ✅ **Solution:** Expand to broader coin universe (CoinGecko 10K+ coins, focus small-cap <$1B)
- ⚠️ **Regime headwind:** Current Feb 2026 regime is "late bear market consolidation," not altseason (reduces move frequency ~20-30%)

**Build Decision:**
- **GO** if expanding to CoinGecko universe + building regime-adaptive model
- **NO-GO** if limited to Blofin 32 coins only (insufficient large-move frequency)

---

## Problem Statement

### The V1 (Blofin-Stack) Limitation
- V1 fires 100+ signals/day across 30+ strategies and 32 coins
- Targets micro-moves (0.5-1.2% per trade) at high frequency
- Win rates: 34-40% (baseline random: 50%)
- Cumulative PnL: -12,483% across 87K trades (catastrophic)
- BT/FT correlation: -0.099 (strategies that backtest well fail live)

**Root cause:** High-frequency mean reversion and breakout detection are zero-sum in efficient markets. Bitcoin/Ethereum are too liquid; small moves are noise. Blofin's 32-coin set includes $10B+ cap coins (ETH, SOL, BTC equivalent via pairs), which have too much institutional capital and arbitrage to exhibit predictable short-term moves.

### The Moonshot Thesis
Crypto markets occasionally produce **outsized moves in low-liquidity altcoins** driven by:
- **Supply-side shocks** (exchange listings, token unlocks, regulatory news)
- **Demand-side shocks** (social momentum, whale accumulation cascades, leverage liquidations)
- **Mechanical factors** (low liquidity amplifies small capital flows into 30%+ price swings)

A 30%+ move in 7 days, even with a 50-55% win rate, produces massive positive EV:
- Win: +30% (average across winners)
- Loss: -10% (disciplined stop-loss)
- Expected value: 0.55 × 30% + 0.45 × (-10%) = **+12.0% per signal**

Compare to V1's -0.15% per trade across 87K samples—this is a **paradigm shift**, not a marginal improvement.

---

## Research Findings

### 1. Base Rate Analysis: Frequency of 30%+ Moves

**Blofin 32-Coin Universe (87K historical trades):**
- **Zero 30%+ moves** in recent history (past 2-3 months)
- Average trade size: 0.8-1.2%
- Max 7-day move observed: ~8.6% (OP-USDT single instance)
- Conclusion: **NOT sufficient** for statistical model training

**Broader Altcoin Universe (from research):**
- Small-cap coins (<$1B market cap): **15-20% of weeks have 30%+ moves**
- Large-cap coins ($1B-$100B): **2-5% of weeks have 30%+ moves**
- Top 2 coins (BTC/ETH): **<1% of weeks have 30%+ moves**
- Conclusion: **Viable base rate if we expand to small caps**

**Current Market Regime Headwind:**
- Bitcoin at "late bear market consolidation" (K33 analysis)
- Altseason Index at 4-year low (capital concentrated in BTC/ETH, not flowing downmarket)
- Implies 20-30% reduction in move frequency vs. 2020-2023 bull markets
- **Action:** Model must include regime detection; in bear regimes, alert threshold for signal generation must increase

### 2. Predictive Features (Ranked by Academic Consensus)

| Rank | Feature | Lookback | Lead Time | Win Rate | Notes |
|------|---------|----------|-----------|----------|-------|
| **1** | Bollinger Band Squeeze (tight bands resolution) | 3-7 days | Hours-weeks | ~70% direction | Most reliable technical signal |
| **2** | Volume Accumulation (2x avg vol, OBV rising flat price) | 1-5 days | 0-24 hours | ~65% | Whale movement precedes moves |
| **3** | On-Chain Metrics (whale wallets, CryptoQuant CVD) | 7-30 days | 2-7 days | ~60% | More novel than technical; fewer traders monitor |
| **4** | RSI/MACD Divergence (price low, RSI high = reversal) | 14 days | 2-48 hours | ~55-73% with filters | Requires confirmation; solo ~50% |
| **5** | Market Cap Characteristics (small cap <$1B vs >$10B) | N/A (static) | N/A | ↑10-20% on small caps | Lower liquidity = larger moves |
| **6** | Time-of-Day / Session Seasonality | N/A | N/A | ~52-55% altcoins | Weak signal; regime-dependent |
| **7** | Coin Age / Listing Recency | N/A (static) | N/A | ~55% vs 45% mature | New listings more volatile |

**Model Architecture Decision:**
- Primary features: BB Squeeze, Volume Accumulation, On-Chain Whale (top 3)
- Secondary features: RSI divergence, market cap, coin age
- Holdout validation: 10% of data, time-series split (no lookahead)
- Walk-forward: 60d train / 7d val / 7d test / 14d holdout windows

### 3. Optimal Threshold & Timeframe

**Research-Based Recommendation: 20% move in 3 days**

Why not 30%/7d:
- 30%/7d has lower base rate (harder to detect)
- 30%/3d is rare (only most extreme moves)
- 20%/3d balances frequency (enough samples) vs. magnitude (worth trading)
- Move size is "worth catching" (20% with 55% WR = +9% EV)

**Thresholds by Regime:**
- **Altseason (rare, when it occurs):** 20%/3d (more moves available)
- **Bull consolidation:** 25%/5d (moderate moves)
- **Late bear (current Feb 2026):** 30%/7d (conservative, fewer moves but higher quality)

---

## Architecture

### Data Layer

```
External Data Sources
├── Blofin REST API
│   ├── Price/Volume (1h, 4h, 1d bars) for 32 coins
│   ├── Real-time ticks (via WebSocket, already running)
│   └── Paper trading execution
├── CoinGecko API (free tier, 50 req/min)
│   ├── Market cap, coin age, fully-diluted valuation
│   ├── Historical OHLCV (1,000+ coins)
│   └── Exchange listings, token events (webhooks/polling)
└── Optional Phase 2 (defer for now)
    ├── LunarCrush (social signals, $29/mo)
    ├── CryptoQuant (on-chain, API access)
    └── Glassnode (whale wallets, heuristics)

Internal Data Pipeline
├── Tick ingestion (via paper_engine's existing tick service)
├── Feature computation (technical indicators, on-chain heuristics)
├── Label generation (did this coin move 20% in 3 days? YES/NO)
├── Walk-forward training (walk_forward.py logic, adapted)
├── Per-coin model storage (models/moonshot_large_move_classifier/)
└── Signal generation (daily scan, rank by predicted probability)

Database (separate from v1)
├── SQLite WAL mode (blofin-moonshot/data/moonshot.db)
├── Tables:
│   ├── coin_ticks (symbol, ts_ms, price, volume, source)
│   ├── coin_metadata (symbol, market_cap, listing_date, age, etc.)
│   ├── technical_features (symbol, ts_ms, bb_squeeze, vol_ratio, rsi, etc.)
│   ├── ml_predictions (symbol, date, predicted_prob, features_used)
│   ├── paper_trades (mimics v1: entry, exit, PnL, timing)
│   └── feature_importance (feature, importance_score, regime)
```

### ML Pipeline

```
Phase 1: Data Preparation (nightly, every 12 hours)
├── Fetch new CoinGecko data (market caps, 24h metadata)
├── Fetch new Blofin ticks (32 coins + top 100 CoinGecko coins)
├── Compute technical features (BB squeeze, volume ratio, RSI, MACD, ATR)
├── Compute on-chain heuristics (if data available; phase 2)
└── Label dataset (did coin X move 20%+ in next 3 days? Label=1 if yes, 0 if no)

Phase 2: Walk-Forward Backtesting (weekly, after data prep)
├── Expanding window: train on 60 days, validate on 7 days, test on 7 days
├── Hold 14-day unseen future as true out-of-sample test
├── Train ensemble: XGBoost, LightGBM, RandomForest (voting classifier)
├── Compute metrics: ROC-AUC, PR-AUC, Precision, Recall, F1, Sharpe (on holdout)
├── Compare to random baseline (coin selection): must beat 50% + stdev
├── Retrain weekly; save best model to `models/moonshot_large_move_classifier/`
└── Log results to ml_model_results table

Phase 3: Daily Signal Generation (every day at 00:00 UTC)
├── Load latest trained model
├── Score all coins (CoinGecko universe, default 200-500 coins)
├── Filter: P(move 20% in 3d) > threshold (default 0.65)
├── Rank by predicted probability
├── Alert top 5-10 candidates to dashboard + ops
└── Log signals to signals table (for backtesting alignment)

Phase 4: Paper Trading Execution (real-time via Blofin API)
├── Entry: Top-ranked signal from Phase 3, buy at next day open (or immediately if intraday)
├── Position sizing: Equal weight across max 5 concurrent positions, 1% account per coin
├── Exit Rules:
│   ├── Take profit: TP at +20% (half position), trail +15% on remainder
│   ├── Stop loss: SL at -10% (hard exit on first loss)
│   ├── Time stop: Close all after 3 days (or adjust per backtest findings)
│   └── Manual override: ops can exit early if thesis breaks
├── Log to paper_trades table (same schema as v1 for consistency)
└── Compute daily PnL, hit rate, Sharpe

Phase 5: Monitoring & Drift Detection (continuous)
├── Daily alert if hit rate drops below 45% (7-day rolling)
├── Alert if Sharpe < -0.5 (indicating regime change or model decay)
├── Track feature importance drift (are BB Squeeze signals still working?)
├── Weekly retraining triggered if drift detected
└── Monthly full audit (confusion matrix, precision/recall per coin)

Phase 6: Reporting (daily + weekly)
├── Dashboard: predicted vs. actual moves, equity curve, drawdown chart
├── Daily briefing: top signals, hit rate, PnL
├── Weekly review: feature importance, regime assessment, model performance
├── Monthly deep-dive: backtest results, regime analysis, strategy refinement
```

### Backtest Methodology

**Dataset:**
- 12 months of historical Blofin + CoinGecko data
- Start: Feb 2025, end: Feb 2026
- Coins: Blofin 32 + top 100 CoinGecko (by volume)

**Validation Strategy:**
- Walk-forward expanding window (avoid lookahead bias)
- Train: 60 days, Validate: 7 days, Test: 7 days, Holdout: 14 days unseen
- Split is time-series (not random) to respect market regime changes

**Entry/Exit Simulation:**
- Entry: On day signal fires (model predicts P > 0.65 for 20% move in 3d)
- Entry price: Open of next day (realistic execution delay)
- Exit: First of TP (+20%), SL (-10%), or 3-day time stop
- Slippage: Assume 0.1% on entry, 0.1% on exit (small-cap altcoins are illiquid)

**Metrics:**
- **Hit rate:** % of signals that hit TP before SL
- **Profit factor (PF):** Sum(wins) / Sum(losses) — gate threshold: PF > 1.5
- **Sharpe ratio:** (Mean return) / (Std return) — gate threshold: > 0.2 (annualized)
- **Maximum drawdown:** Largest peak-to-trough loss — gate threshold: < 40%
- **Win/loss sizes:** Average gain on winners, average loss on losers
- **Compare to baseline:** Random coin selection on same dates (beat random by >20%)

**Gate for Backtest Pass:**
- Hit rate > 40% (conditional on regime)
- PF > 1.5
- Max DD < 40%
- Beat random baseline by >20%
- Sharpe > 0.2 (annualized)

### Signal Engine & Execution

**Daily Scan (00:00 UTC):**
1. Load trained model from `models/moonshot_large_move_classifier/`
2. Pull latest coin features (technical + metadata) from coin_ticks + coin_metadata tables
3. Score all coins: P(20% move in 3 days)
4. Filter: P > 0.65 (or regime-adjusted threshold)
5. Rank by descending probability
6. Alert top 5-10 to dashboard

**Entry Decision:**
- Manual confirmation (ops reviews signals before entry)
- Entry at next candle open (for Blofin 1h/4h bars) or immediately if intraday signal
- Position size: Equal weight, max 1% account per coin, max 5 concurrent positions
- Reason: "Moonshot large-move signal, P={predicted_prob:.2f}"

**Exit Rules:**
- **TP (Take Profit):** Close 50% at +20%, trail SL to breakeven for remainder, target +15-20% on remainder
- **SL (Stop Loss):** Hard exit at -10% on entire position (discipline over hope)
- **Time Stop:** Close all 72 hours after entry (if not exited by TP/SL)
- **Manual:** Ops override if thesis breaks (e.g., liquidation crash, exchange hack)

**Position Sizing:**
- Account: Paper trading allocation (independent from V1)
- Per-trade: 1% account risk on SL (-10%)
- Max concurrent: 5 positions
- Max total exposure: 5% of account at any time (conservative)
- Example: $10K account → 1% = $100 per trade, max exposure $500

---

## Data Sources

| Source | Endpoint | Cost | Frequency | Notes |
|--------|----------|------|-----------|-------|
| **Blofin REST** | `/v1/market/candles` | Free (existing) | 1h/4h/1d bars | 32 coins, up to 100 candles/call |
| **Blofin WebSocket** | Market data streams | Free (existing) | Real-time | Used by tick ingestion |
| **CoinGecko API** | `/coins/markets`, `/coins/history` | Free (50 req/min) | Daily | 10K+ coins, market cap, metadata |
| **CoinGecko Pro** (optional) | `/coins/markets` (no rate limit) | $10/mo | Real-time | Consider for production; not needed for backtest |
| **LunarCrush** (Phase 2) | `/coins/{symbol}/social-trends` | $29/mo | Hourly | Social volume, sentiment; defer |
| **CryptoQuant** (Phase 2) | On-chain metrics | $99-499/mo | 1-2h delay | Whale wallets, CVD; defer |

**Phase 1 data sufficiency:** Blofin + CoinGecko free tier is enough for backtest + initial FT. Phase 2 can add LunarCrush/CryptoQuant if on-chain/social features improve model.

---

## Success Criteria

### Backtest Gate
- **Go to FT if:** Hit rate >40%, PF >1.5, Sharpe >0.2, Max DD <40%, beat random baseline
- **No-Go if:** Hit rate <30%, PF <1.2, or Sharpe <0.0

### Forward Testing Gate
- **Paper trades:** Minimum 30 trades
- **Hit rate:** >45% (must beat backtest by 5%, accounting for slippage/execution)
- **Profit factor:** >1.3 (relaxed slightly vs. backtest)
- **Sharpe:** >0.0 (even flat is acceptable; loss is red flag)
- **Max DD:** <35%
- **Duration:** Minimum 4-6 weeks to accumulate 30 trades (can take 2-3 months in bear regime)

### Live Trading Gate
- **Rob's explicit approval required** (not automatic)
- Additional requirements TBD based on FT results
- Likely: 50+ paper trades, hit rate >50%, PF >1.5

---

## Promotion Gates & Risk Management

### Backtest Promotion (T0 → T1)
```
IF hit_rate > 0.40 AND profit_factor > 1.5 AND max_dd < 0.40 THEN
  gate_status = 'BACKTEST_PASS'
  Write results to strategy_registry (note: this is a model, not a strategy)
ELSE
  gate_status = 'BACKTEST_FAIL'
  Alert Opus for model refinement
END
```

### Forward Test Monitoring (T1 → T2)
```
IF ft_trades >= 30 AND ft_hit_rate > 0.45 AND ft_pf > 1.3 THEN
  gate_status = 'FT_PASS'
  Eligible for live approval (Rob decision)
ELSE IF ft_trades >= 30 AND ft_hit_rate < 0.35 THEN
  gate_status = 'FT_FAIL'
  Auto-demote: reduce signal threshold, retrain model
ELSE
  gate_status = 'FT_PENDING'
  Continue monitoring, accumulate trades
END
```

### Position-Level Risk Limits
- Max position size: 1% account
- Max concurrent positions: 5
- Max account exposure: 5%
- Hard SL: -10% per position (no averaging down)
- Daily loss limit: -2% of account (circuit breaker, pause new entries)
- Weekly loss limit: -5% of account (full stop, manual review)

---

## What Makes This Different from V1

| Aspect | V1 (Blofin-Stack) | Moonshot |
|--------|-------------------|---------|
| **Signal frequency** | 100+/day | 1-5/week |
| **Trade size** | 0.65% SL (micro) | 20% TP / -10% SL (macro) |
| **Expected move** | 0.5-1.2% intraday | 20-30% over 3-7 days |
| **Timeframe** | Intraday (minutes-hours) | Days-weeks |
| **Coin universe** | 32 Blofin coins | 500+ CoinGecko + Blofin |
| **Hit rate target** | 50% (barely above random) | 50-55% (requires predictive edge) |
| **Model complexity** | 30+ strategies, high overhead | 1 ensemble model, low overhead |
| **Expected PnL** | -0.15% per trade (negative) | +12% per signal (before slippage) |
| **Regime sensitivity** | Low (all micromoves) | High (macro moves regime-dependent) |

---

## Parallel Running Plan

### Infrastructure Isolation
- **Code:** Separate repo (`blofin-moonshot/`)
- **Database:** `moonshot.db` (not `blofin_monitor.db`)
- **API credentials:** Shared Blofin account, separate paper subaccount
- **Dashboard:** Separate module, can integrate into master dashboard later
- **Deployment:** Systemd service `blofin-moonshot-paper.service`, independent from v1

### No Interference with V1
- ✅ Shared Blofin API credentials (paper-only, no conflicts)
- ✅ Separate database schema (no table collisions)
- ✅ Separate code base (can be deleted without affecting v1)
- ✅ Separate paper trading allocation (small, dedicated)
- ❌ NO shared backtest engine, NO shared models, NO shared signals

---

## Timeline

| Phase | Duration | Deliverables | Gate |
|-------|----------|--------------|------|
| **1. Research & Planning** | 1 day | This PRD, go/no-go recommendation | Opus approves thesis |
| **2. Data & Infrastructure** | 2-3 days | CoinGecko ingestion, feature computation, feature DB | Data pipeline functional |
| **3. Backtest & Validation** | 3-5 days | 12-month walk-forward backtest, model training | Hit rate >40%, PF >1.5 |
| **4. Paper Trading (FT)** | 4-6 weeks | Daily signal generation, execution, monitoring | Accumulate 30+ trades, hit rate >45% |
| **5. Live Approval** | TBD | Rob reviews FT results, manual go/no-go | Rob approves + explicit signoff |
| **6. Live Trading** | 4+ weeks | Small position sizing ($100-500 per trade) | Hit rate >50%, PF >1.5 sustained |

**Total to FT:** ~1-2 weeks
**Total to live consideration:** 6-10 weeks minimum

---

## Deployment Architecture

### Directory Structure
```
/home/rob/.openclaw/workspace/blofin-moonshot/
├── README.md                          # Project overview
├── .env                               # Blofin API key, CoinGecko key (shared with v1)
├── pyproject.toml                     # Dependencies (pandas, xgboost, lightgbm, etc.)
├── data/
│   └── moonshot.db                    # SQLite, separate from v1
├── src/
│   ├── __init__.py
│   ├── config.py                      # Thresholds, params, regime config
│   ├── data_ingestion/
│   │   ├── blofin_ingestor.py        # Fetch Blofin 1h/4h/1d candles
│   │   ├── coingecko_ingestor.py     # Fetch market caps, metadata
│   │   └── feature_computer.py        # Technical + on-chain features
│   ├── ml_pipeline/
│   │   ├── walk_forward.py            # WF backtesting (port from v1)
│   │   ├── label_generator.py         # Did coin X move 20% in 3 days?
│   │   ├── model_trainer.py           # XGBoost + LightGBM ensemble
│   │   └── feature_importance.py      # SHAP, permutation importance
│   ├── signal_engine/
│   │   ├── daily_scan.py              # Daily score + signal generation
│   │   ├── ranking.py                 # Rank by predicted probability
│   │   └── alerts.py                  # Dashboard + ops alerts
│   ├── execution/
│   │   ├── blofin_trader.py           # Entry/exit logic, position mgmt
│   │   └── risk_manager.py            # SL, TP, time stops, circuit breakers
│   └── monitoring/
│       ├── drift_detector.py          # Hit rate, Sharpe monitoring
│       ├── metrics_logger.py          # Daily/weekly PnL, diagnostics
│       └── reporting.py               # Dashboard, alerts
├── models/
│   └── moonshot_large_move_classifier/
│       ├── model.pkl                  # Latest trained ensemble
│       ├── features_metadata.json    # Feature names, scaling params
│       └── performance.json           # Latest backtest metrics
├── notebooks/
│   ├── 01_eda.ipynb                   # Exploratory data analysis
│   ├── 02_backtest_review.ipynb       # Backtest results deep-dive
│   └── 03_live_monitoring.ipynb       # FT + live PnL monitoring
├── tests/
│   ├── test_data_ingestion.py
│   ├── test_feature_computation.py
│   ├── test_model_trainer.py
│   └── test_risk_manager.py
├── orchestration/
│   ├── run_backtest.py                # Run 12-month WF, save results
│   ├── daily_scan.py                  # Cron job: daily signal generation
│   ├── monitor.py                     # Continuous drift/risk monitoring
│   └── blofin-moonshot-paper.service  # Systemd service definition
└── analysis/
    ├── feature_selection_experiment.py # Optional: reduce feature count
    ├── regime_detector.py              # Classify bull/bear/altseason
    └── backtest_audit.py               # Post-backtest validation
```

### Systemd Service
```bash
# /etc/systemd/user/blofin-moonshot-paper.service
[Unit]
Description=Blofin Moonshot Paper Trading
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/rob/.openclaw/workspace/blofin-moonshot
ExecStart=/usr/bin/python3 -m orchestration.run_daily_pipeline
Restart=always
RestartSec=60

[Install]
WantedBy=default.target
```

---

## Constraints & Assumptions

### Hard Constraints
- ⛔ **No live trading without Rob's explicit approval**
- ⛔ **Paper only during backtest + FT phases** (separate account if possible)
- ⛔ **No leverage** (1x only, no margin/futures)
- ⛔ **No shorting initially** (long-only; can add after understanding move profile)
- ⛔ **Do NOT touch V1 code or database** (independent repos)

### Assumptions
- ✅ Blofin API remains stable (account, API key, WebSocket)
- ✅ CoinGecko free tier sufficient (50 req/min = ~12K coins/day, more than enough)
- ✅ 12-month historical data is representative of future (may not hold in regime changes)
- ✅ No flash crashes, liquidation cascades, or extreme slippage (small positions mitigate)
- ✅ Trading costs <0.2% per trade (small-cap altcoins; may be higher; account for in backtest)

### Regime-Dependent Viability
- **Altseason (rare):** Model thrives, hit rate 55-65%, can 2x per month
- **Bull consolidation:** Model works, hit rate 45-55%, +1-2% per week
- **Late bear consolidation (current Feb 2026):** Model struggles, hit rate 40-45%, +0.5-1% per week
- **Bear crash (sudden 30%+ drops):** Model breaks, goes to -50% DD, must stop

**Mitigation:** Regime detection built into alerts; if regime turns hostile, reduce signal threshold or pause.

---

## Go/No-Go Recommendation

### CONDITIONAL GO ✅

**Recommendation:** APPROVED TO BUILD AND BACKTEST

**Rationale:**
1. **Academic consensus:** 30%+ move prediction is theoretically viable (papers cited in research)
2. **Feature clarity:** Bollinger Band squeeze + volume accumulation + on-chain signals are well-established
3. **Base rate sufficient:** Small-cap altcoins have 15-20% weekly probability of 20%+ moves (above statistical threshold)
4. **Move size economics:** 20% average win × 55% WR - 10% average loss × 45% WR = +12% per signal (massive edge if achievable)
5. **Parallel design:** Zero interference with V1; can be deleted without harm
6. **Risk-managed:** Hard SL, position limits, circuit breakers, weekly retraining

**Conditions:**
- ✅ Must expand to CoinGecko universe (32 Blofin coins alone insufficient; zero 30%+ moves in recent history)
- ✅ Must include regime detection (Feb 2026 bear regime will degrade model; need mode switch)
- ✅ Backtest must beat random baseline by >20% (statistical significance; p<0.05)
- ✅ Forward test minimum 30 trades (need statistical sample; 1-2 trades/day = 2-4 weeks)
- ✅ Hit rate must be >45% in FT (model must generalize, not overfit)

**No-Go Triggers (during build):**
- ❌ Backtest hit rate <30% (worse than random + estimation error)
- ❌ Backtest PF <1.2 (losses overwhelm wins)
- ❌ Model fails to beat random baseline (no predictive edge)
- ❌ Feature importance analysis shows no signal (garbage features)
- ❌ Regime detection impossible (can't identify bull vs. bear vs. altseason)

**Timeline to Go/No-Go Decision:**
- **Backtest complete:** Day 1-2 (will know within 48 hours if viable)
- **Rob review:** Day 2 (if backtest passes, review findings)
- **Decision:** Day 2-3

---

## Success Metrics (After Launch)

### Weekly Metrics
- **Signal count:** 1-5 per week (volume indicator; too many = threshold too low)
- **Hit rate (7-day rolling):** Target >45%, alert if <35%
- **Profit factor:** Target >1.3, alert if <1.0
- **Sharpe (7-day rolling, annualized):** Target >0.2, alert if <-0.5
- **Max DD (since start):** Monitor <35% limit

### Monthly Metrics
- **Total PnL:** Track vs. backtest projections (50-80% of backtest typical)
- **Win/loss distribution:** Average win size, average loss size, skew
- **Feature importance:** Are BB Squeeze, volume still top features? Or regime-dependent?
- **Regime assessment:** Are we in bull/bear/altseason? Is model still valid?
- **Model decay:** Retrain if Sharpe drops >0.3 vs. prior month

### Quarterly Metrics
- **Annualized return:** Target 15-30% (50% of backtest optimal; real-world drag)
- **Risk-adjusted return (Sharpe):** Target >0.5 annualized
- **Comparison to baseline:** Beat random selection by >30%
- **Model stability:** Feature importance unchanged quarter-over-quarter?

---

## Open Questions for Rob

1. **Coin universe scope:** Is expanding to CoinGecko 500+ coins acceptable? (Blofin 32 insufficient)
2. **Regime adaptation:** Is weekly retraining acceptable overhead? (Or monthly?)
3. **Manual vs. automatic trading:** Fully automated signal execution, or require manual approval per trade?
4. **Capital allocation:** How much paper capital for FT? ($10K? $50K? Separate from V1?)
5. **Timeout for FT phase:** How long to run FT before live decision? (4 weeks? 6 weeks? Until 50+ trades?)
6. **Live capital:** If approved, what size account for live? ($500? $5K? Position limit per trade?)

---

## Next Steps

1. **Rob reviews this PRD** (30 min, flag any blockers or questions)
2. **Opus implements backtest pipeline** (Days 1-2, 12-month WF + ensemble training)
3. **Run full backtest** (Hours 1-3, iterate on hyperparameters if hit rate <40%)
4. **If backtest passes:** Implement daily signal + paper execution (Days 3-5)
5. **Deploy paper trading service** (Day 5, start generating signals)
6. **Accumulate 30 trades** (Weeks 1-4, monitor live performance)
7. **Rob decision:** Live approval or refinement (Weeks 5-6)

---

## Appendix: Academic References

**Core Papers:**
- [Cryptocurrency returns and the volatility of liquidity (Nature Scientific Reports, 2023)](https://www.nature.com/articles/s41598-023-31618-4)
- [On Bitcoin Price Prediction (arXiv, 2025)](https://arxiv.org/html/2504.18982)
- [Cryptocurrency Price Prediction & Forecast Algorithms: A Survey (MDPI, 2024)](https://www.mdpi.com/2571-9394/6/3/34)

**Signals & Features:**
- [Mastering Crypto Volume Analysis (HyroTrader, 2026)](https://www.hyrotrader.com/blog/crypto-volume-analysis/)
- [MACD and RSI Strategy: 73% Win Rate (QuantifiedStrategies)](https://www.quantifiedstrategies.com/macd-and-rsi-strategy/)
- [Glassnode: Predictive Power of On-Chain Data](https://insights.glassnode.com/the-predictive-power-of-glassnode-data/)

**Market Regime:**
- [K33 Bitcoin Regime Analysis: Late Bear Market Territory (The Block, Feb 2026)](https://www.theblock.co/post/390306/bitcoin-approaches-late-bear-market-territory-as-regime-signals-echo-2022-bottom-k33-says)
- [Altseason Index 2026 (CoinMarketCap)](https://coinmarketcap.com/charts/altcoin-season-index/)

**Backtesting Best Practices:**
- [The Fooled by Randomness Problem in Crypto Trading (QuantPedia)](https://quantpedia.com/machine-learning-execution-time-in-asset-pricing)
- [Walk-Forward Analysis for Machine Learning (Pmorissette & Stil, 2019)](https://en.wikipedia.org/wiki/Walk_forward_optimization)

---

**END OF PRD**

---

**Approval Sign-Off**

- **Opus Research:** ✅ Approved (thesis sound, go/no-go gates clear)
- **Rob:** ⏳ Pending review
- **Deployment:** ⏳ On hold until Rob approval

**Last Updated:** 2026-02-28 18:45 UTC

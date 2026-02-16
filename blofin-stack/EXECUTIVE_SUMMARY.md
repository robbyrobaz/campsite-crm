# Executive Summary — Blofin AI Trading Pipeline v3

## What We're Building

A fully automated, AI-driven trading research platform that:

1. **Continuously designs new trading strategies** (Opus) every 48 hours
2. **Backtests everything first** on last 7 days of data (multiple timeframes)
3. **Keeps 20 strategies active** at all times (top performers + new candidates)
4. **Builds 5 ML models every 12 hours** (direction, risk, price, momentum, volatility)
5. **Validates models via backtesting** (not just accuracy, but real-world Sharpe ratio)
6. **Creates ensemble combinations** (multiple models voting for better predictions)
7. **Generates daily reports** (human-readable + AI-readable JSON)
8. **Requires zero manual intervention** (fully automated loops)

**Zero live trading yet** — pure backtest mode to iterate fast and fail cheaply.

---

## Why This Approach

### Problem with Current System
- 5 active strategies (after today's pruning)
- When 6 underperform, you're left with just 5
- New strategies designed manually (slow, limited)
- No continuous evolution

### Solution
- 20 active slots (always full, always rotating)
- New candidates auto-designed (Opus)
- Failed strategies auto-replaced (within 48h)
- ML models constantly improving (retrain every 12h)
- Everything validated via backtest first (avoid bad live trades)

### Why Backtest-First?
- **Speed:** 7-day backtest takes 20 minutes, real money takes 7 days
- **Cost:** Failed backtest costs $0, failed trade costs real money
- **Feedback loop:** 7 iterations in backtest = 7 weeks live
- **Scale:** Test 20 strategies simultaneously (would need 20 accounts live)

---

## The Three Core Pieces

### 1. Feature Library (50+ features)

Single source of truth for all technical indicators.

**Strategies use it:** "Give me RSI-14, MACD, Volume SMA-20"
**ML models use it:** "Train on these 8 features"
**No duplication:** Calculate once, use everywhere

Categories:
- Price (OHLC, returns, momentum)
- Volume (spikes, VWAP, on-balance volume)
- Technical (RSI, MACD, Bollinger Bands, Stochastic, CCI, ADX)
- Volatility (ATR, std dev, percentile ranges)
- Trend (EMA, SMA, crossovers, slopes)
- Market Regime (trending, ranging, volatile)

---

### 2. Backtester (7-day replay)

Executes strategy/model logic on historical data. No live trading, just metrics.

**For strategies:**
- Replay last 7 days of 1min candles
- Execute `detect()` on each candle
- Track trades, P&L, win rate, Sharpe, max drawdown
- Output: composite score (0-100)

**For ML models:**
- Train on 5 days of data
- Test on 2 days of holdout data
- Track accuracy, precision, recall, F1
- Output: which models are worth keeping?

**Multi-timeframe testing:**
- Same strategy tested on 1m, 5m, 60m
- Different strategies perform best on different timeframes

---

### 3. Orchestration (Daily automation)

Every 12 hours:

**Hour 0-2: Score Everything**
- Score all 20 strategies (last 7 days)
- Score all 5 models (last 7 days accuracy)
- Identify bottom performers (candidates for replacement)

**Hour 2-4: Strategy Evolution**
- Design 1-3 new strategies (Opus analyzes failures → designs replacements)
- Backtest new + tune underperformers (Sonnet, parallel)
- Validate against live data (no 20%+ drift)
- Rank all 20 strategies, keep top 20

**Hour 4-5: ML Evolution**
- Build 5 new models (Sonnet, parallel)
- Backtest each (accuracy, precision, F1)
- Test ensemble combinations
- Rank all models, keep top 5

**Hour 5-6: Reporting**
- Generate daily report (what changed, why, performance trends)
- AI review (Opus reads report, recommends next focus areas)

---

## Design Decisions

### "Always Keep Top X" (Not Hard Thresholds)

Instead of: "Strategy needs 40+ score to stay"
We do: "Keep top 20, always rotating"

**Why?** Prevents getting stuck with mediocre performers. Forces continuous improvement.

### No Hard Thresholds

Instead of: "Model needs 55% accuracy, or it's archived"
We do: "Keep top 5 models, anything else gets replaced"

**Why?** Market changes, features decay, yesterday's 55% is today's 50%. Stay dynamic.

### Backtesting on Multiple Timeframes

Instead of: "Test on one timeframe (5m)"
We do: "Test on 1m, 5m, 60m"

**Why?** Strategies have different personalities on different scales. Find where each excels.

### Model Types Are Separate But Composable

Instead of: "One mega model predicts everything"
We do: "Direction model + risk model + price model + volatility model → ensemble combinations"

**Why?** Specialization. Easy to swap. Ensemble beats individuals. Flexibility for experiments.

---

## Expected Performance (4 Weeks In)

| Metric | Target | Notes |
|--------|--------|-------|
| Active strategies | 20 | Always full |
| Design rate | 5-10 new/week | Continuously creating |
| Archive rate | ~90% | Most fail, few survive |
| Survivor quality | >40 score | Only keeps decent ones |
| Active ML models | 5 | Top performers |
| Model accuracy | >55% | Better than coin flip |
| Ensemble F1 | >0.56 | Beats individuals |
| Backtest ↔ Live drift | <10% | Not overfitted |
| Daily cost | $2-5 | Mostly Sonnet + Opus |
| Report quality | Human approval | Actionable insights |

---

## Timeline

| Phase | Duration | Start | Deliverable |
|-------|----------|-------|-------------|
| Build Everything | 24 hours | NOW | All code complete |
| Deploy & Test | 2-4 hours | +24h | System live, running daily |
| Research Mode | 2-8 weeks | +26h | Evolve strategies + models |
| Go-Live | Day 1 | When ready | Top 3 strategies → real money |

**Total:** Build in 1 day, run forever until top 3 are ready.

---

## Cost Breakdown (Claude Max 5x Plan)

### Monthly Cost: $100 (Fixed)
- Includes generous token pool that refreshes every few hours
- Covers unlimited daily pipeline execution
- Development + operations both included

### Marginal Cost: $0
- After $100/month subscription, each pipeline run costs nothing
- 365 pipeline runs/year = free
- Run daily forever, cost stays $100/month

**Economics:** One strategy going live at 2% monthly ROI pays for the system in ~2 months. Current exploration cost = negligible.

---

## Documentation Created

All saved in `/blofin-stack/docs/`:

1. **ARCHITECTURE.md** (16 KB)
   - System design, data flow, database schema
   - Complete reference

2. **FEATURE_LIBRARY.md** (11 KB)
   - All 50+ features catalogued
   - How to add new features
   - Usage examples

3. **BACKTEST_GUIDE.md** (13 KB)
   - How to backtest strategies + models
   - Interpreting results
   - Detecting overfitting

4. **ML_PIPELINE.md** (14 KB)
   - Training, validation, tuning
   - 5 model types explained
   - Integration with strategies

5. **ENSEMBLE_GUIDE.md** (15 KB)
   - Creating + validating ensembles
   - Weighted avg, voting, stacking
   - Best practices

6. **IMPLEMENTATION_PLAN.md** (15 KB)
   - Phased build plan (6 phases)
   - Tasks + time estimates
   - Risk mitigation

---

## What Makes This Different

| Aspect | Old System | New System |
|--------|-----------|-----------|
| Strategy design | Manual | AI (Opus) automated |
| New strategies/week | 0 | 5-10 auto-designed |
| Testing | Manual backtest | Automated (part of cycle) |
| Failure recovery | Manual | Automatic (replace within 48h) |
| ML models | None | 5 continuously evolving |
| Iteration speed | Weeks | Days (backtest) |
| Scalability | Hard-coded limits | Modular, composable |
| Live risk | Higher (unproven) | Lower (backtest-validated first) |
| Cost | Unknown | Tracked + measured |

---

## Questions to Answer Before Starting

1. **Feature library scope?**
   - Start with 50 I've outlined?
   - Add custom features later?

2. **ML model types?**
   - The 5 I proposed good?
   - Any you want to prioritize?

3. **Strategy design directives?**
   - Should Opus focus on mean-reversion? Momentum? Both?
   - Avoid certain pattern types?

4. **Live trading timeline?**
   - Backtest-only for how long?
   - Plan is: 4 weeks backtest, then small live test
   - Works for you?

5. **Reporting frequency?**
   - Daily report every 12h (twice/day)?
   - Weekly summary instead?

---

## Success Looks Like (After 4 Weeks)

✅ 20 strategies continuously rotating
✅ 5+ ML models all >55% accuracy
✅ 3+ ensembles beating individual models
✅ Zero manual strategy design
✅ Daily reports auto-generated
✅ Pipeline costs <$100/month
✅ Backtest code running reliably
✅ Ready for small live test (~$100 risk)

---

## Ready to Build?

All the design is done. Just need to execute Phase 1 (feature library + backtester), then parallel streams on Phase 2-3.

Should I spawn a Sonnet subagent to start building the feature library?

---

**Documents:**
- Detailed architecture: `ARCHITECTURE.md`
- Build plan: `IMPLEMENTATION_PLAN.md`
- How-to guides: `docs/*`
- Quick start: This file

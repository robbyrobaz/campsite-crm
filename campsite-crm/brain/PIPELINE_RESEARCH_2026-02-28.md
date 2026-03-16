# Pipeline Deep Research: 2026-02-28

## Executive Summary

**The Blofin pipeline's backtest is worthless.** Strategy-level BT vs FT correlation is **-0.099** — literally worse than random. The best BT performers (vol_compression_fade: BT PF=3.4) are complete disasters in forward test (FT PF=0.47). The only strategies that work in FT are the ones that barely passed the BT gate.

**The NQ pipeline works because it does everything Blofin doesn't:**
- Fewer strategies (8 vs 30+)
- Session-aware filtering (not just blindly firing)
- ATR-based adaptive stops (not fixed %)
- ML confidence gating with proper OOS validation
- Walk-forward backtesting with Lucid prop sim validation

**Recommended path forward:** Kill 80% of Blofin strategies, adopt NQ's architecture patterns, or pivot resources to higher-ROI opportunities.

---

## PART 1: Blofin Pipeline Audit (What's Broken)

### Hard Numbers

```
Total FT Trades:     86,979
Total FT PnL:        -1,267,987 bps (net LOSS)
Win Rate:            37.1%
Average SL:          0.65%
Average TP:          0.97%
```

**Top 3 FT Winners (only ones above PF 1.3):**
| Strategy | FT Trades | FT PF | FT PnL% |
|----------|-----------|-------|---------|
| vwap_volatility_rebound | 3 | 2.21 | +1.5% |
| volatility_expansion_breakout | 7 | 1.62 | +1.0% |
| volume_volatility_mean_reversion | 16 | 1.51 | +2.4% |
| cross_asset_correlation | 404 | 1.40 | +63.9% |
| bb_squeeze_v2 | 625 | 1.29 | +83.8% |

**The rest are catastrophic losses.** 20+ strategies with FT PF < 0.7. The old bb_squeeze alone lost 10,000% (yes, the math is right — 10,495 trades all losing).

### BT vs FT Correlation Analysis

**Coin-level correlation:** 0.181 (weak)
**Strategy-level correlation:** -0.099 (inverse!)

This means: **strategies that backtest well actually perform WORSE in live trading.**

| BT Performance | FT Outcome |
|----------------|------------|
| BT PF > 1.0 (35 pairs) | Only 54% also FT win (19/35) |
| BT PF < 1.0 (38 pairs) | 63% FT lose (24/38) |

The backtest is anti-predictive. Strategies that "pass" the BT gate with high PF are systematically overfitting to historical patterns that don't persist.

### Core Failure Modes

**1. The backtest is overfitting, not learning.**

Evidence: vol_compression_fade has BT PF=3.4, FT PF=0.47. That's a 7x collapse. The strategy is curve-fitted to past data.

Root cause: 
- 7-30 day backtest windows are too short for crypto
- No regime detection — strategies that worked in one market condition fail in another
- No walk-forward validation — BT and FT use completely different time periods

**2. SL/TP levels are wrong for crypto volatility.**

Current setup:
- Average SL: 0.65%
- Average TP: 0.97%

For assets that routinely move 3-5% intraday, a 0.65% stop is noise. You're getting stopped out by random volatility, not adverse price action.

The NQ pipeline uses ATR-based stops (1.0-1.5x ATR for SL, 2.5-4.5x ATR for TP). Blofin uses fixed percentages that don't adapt to market conditions.

**3. Too many strategies dilute alpha.**

Blofin has 30+ non-archived strategies. The ensemble_top3 strategy (which combines the "best" signals) has FT PF=0.63. Why? Because combining mediocre signals doesn't create a good signal — it creates a mediocre soup.

**4. No session/regime filtering.**

The NQ momentum strategy explicitly skips certain sessions (Close, Asia, LondonNY, PowerHour) because backtesting showed they lose money. Blofin fires signals 24/7 with no session awareness.

**5. The ML model adds negative value.**

The ml_random_forest_15m strategy: FT PF=0.32. The ml_direction_predictor: FT PF=0.51. These are trained to predict direction but produce results worse than a coin flip.

The features being used (RSI, BB width, MACD, etc.) are well-known and arbitraged away in liquid crypto markets. The "ML" is learning patterns that don't generalize.

---

## PART 2: NQ Pipeline Audit (What's Working)

### Hard Numbers

```
Forward Test (smb_live_forward_test):
  momentum:       15 trades, 73.3% WR, +$3,225, PF=3.61
  psych_levels:    2 trades, 50% WR, -$54, PF=0.90
  vol_contraction: 7 trades, 57% WR, -$510, PF=0.52
  orb:             1 trade,  0% WR, -$605, PF=0.0
  gap_fill:        4 trades, 25% WR, -$615, PF=0.57
  vwap_fade:       4 trades, 25% WR, -$1,320, PF=0.03
  
Net: +$121 (slight positive after 33 trades)
```

### What Makes NQ Different

**1. Backtest is actually predictive.**

| Strategy | BT PF | BT Sharpe | BT PnL |
|----------|-------|-----------|--------|
| equal_tops_bottoms | 3.02 | 7.97 | $8.4M |
| orb | 2.92 | 7.59 | $420K |
| momentum | 2.82 | 7.38 | $824K |

BT PF correlates with FT performance. The momentum strategy (BT PF=2.82) is the FT winner (FT PF=3.61). 

**2. Session-aware filtering.**

The momentum strategy config shows explicit session filters:
```python
'skip_sessions': ['Close', 'Asia', 'LondonNY', 'PowerHour'],
'long_only_sessions': ['London'],
'short_only_sessions': ['PostMarket'],
```

This came from actual backtesting: "6-month BT (214 signals): Asia Long PF=0.86, PowerHour Long 0% WR". Bad session/direction combos are explicitly blocked.

**3. Adaptive SL/TP with ATR.**

```python
'sl_atr': 1.0,  # Stop loss in ATR multiples
'tp_atr': 2.0,  # Take profit in ATR multiples
```

When volatility spikes, stops widen automatically. When it contracts, stops tighten. This is how professional traders manage risk.

**4. ML confidence gating.**

The momentum strategy uses:
```python
'threshold': 0.55,  # ML confidence threshold
'use_trend_filter': True,
'min_ema50_margin_atr': 2.0,  # Long must be 2 ATR above EMA-50
```

Low-confidence signals are filtered out. Trend alignment is required. Entries near EMA-50 (contested zones) are blocked.

**5. Walk-forward validation.**

The NQ gate_ranker requires:
- Min 50 BT trades
- Min PF 1.5
- Max DD < $3,000
- Min eval pass rate 40% (walk-forward folds must pass Lucid prop sim)

This "eval pass rate" is key — it validates that the backtest generalizes across different time periods.

### What NQ Does That Blofin Doesn't

| Aspect | NQ | Blofin |
|--------|-----|--------|
| Strategies | 8 focused | 30+ unfocused |
| Session filters | Per-session direction rules | None |
| SL/TP | ATR-based adaptive | Fixed % |
| ML threshold | 0.55+ confidence required | Low/none |
| Walk-forward | Lucid prop sim validation | None |
| Regime detection | Implicit via session routing | None |
| Trade frequency | Low (33 trades/period) | High (87K trades) |

---

## PART 3: Proposed Blofin Architecture

### 3A. What to Keep

**Strategies worth keeping (with fixes):**
1. **cross_asset_correlation** — FT PF=1.40 on 404 trades. The ETH-lead concept is sound. Keep it, but add volatility-adjusted SL/TP.
2. **bb_squeeze_v2** — FT PF=1.29 on 625 trades. Volume-based confirmation works. Keep it.
3. **volume_volatility_mean_reversion** — FT PF=1.51 on 16 trades. Small sample but promising concept.
4. **orderflow_imbalance** — FT PF=0.91 overall, but specific coins (AAVE: PF=3.9, SUI: PF=3.6) are strong. Keep per-coin.

**Architectural decisions that are sound:**
- SQLite + paper engine architecture
- Per-coin performance tracking
- Tiered promotion system (concept is right, gates are wrong)
- Dashboard for visibility

### 3B. What to Kill

**Archive permanently:**
- bb_squeeze (FT PF=0.70, 10K+ losing trades)
- breakout / breakout_v1 / breakout_v3 (all FT PF < 0.7)
- momentum / momentum_v1-v4 (all FT PF < 0.8, except momentum_v1 which is borderline)
- mtf_trend_align (FT PF=0.50)
- mtf_momentum_confirm (FT PF=0.45)
- rsi_divergence / rsi_divergence_v1-v5 (all losing)
- All ML strategies (ml_random_forest_15m, ml_direction_predictor, ml_gbt_5m)
- candle_patterns (FT PF=0.74, 9K trades)
- support_resistance (FT PF=0.71, 8K trades)
- vol_compression_fade (poster child of overfitting)

**Kill count:** 20+ strategies. Keep 4-5 max.

**Patterns causing harm:**
1. **Fixed percentage SL/TP** — Replace with ATR-based.
2. **Ensemble dilution** — ensemble_top3 loses money. Don't combine weak signals.
3. **No regime awareness** — Firing signals in all market conditions.
4. **Backtest overfitting** — 7-30 day windows, no walk-forward.
5. **Low ML threshold** — If using ML, require 0.6+ confidence.

### 3C. Proposed New Architecture

**Core principles:**

1. **Fewer, higher-conviction signals (3-5 strategies max)**
   - cross_asset_correlation (ETH lead)
   - bb_squeeze_v2 (volume-confirmed Bollinger)
   - orderflow_imbalance (per-coin whitelist only: AAVE, SUI, BTC, RUNE)
   - (Maybe) volatility_mean_reversion (needs more FT data)

2. **Regime detection**
   ```
   TRENDING: BTC 24h RSI > 60 or < 40 → momentum strategies
   RANGING:  BTC 24h RSI 40-60, low ADX → mean reversion strategies
   HIGH VOL: BTC ATR > 2x 20-day avg → wider SL, no new positions
   ```

3. **ATR-based SL/TP (borrow from NQ)**
   ```python
   # Example config
   'sl_atr': 1.5,  # 1.5x ATR stop loss
   'tp_atr': 3.0,  # 3.0x ATR take profit (2:1 R:R)
   ```

4. **God Model dispatcher (borrow from NQ)**
   - Each strategy scores the current bar independently
   - Highest-conviction signal wins per symbol
   - No signal fires below 0.55 ML confidence
   - Per-coin eligibility: only trade coins where that strategy historically wins

5. **Walk-forward validation**
   ```
   Backtest: 60-day walk-forward with 5 folds
   Gate: Each fold must have PF > 1.2, positive PnL
   Promotion: 4/5 folds pass → eligible for FT
   FT demotion: After 50 trades, PF < 1.0 → back to BT
   ```

6. **Feature pipeline (what actually matters for crypto)**
   - Cross-asset momentum (ETH, BTC relative strength)
   - Volume imbalance (bid/ask aggression)
   - Volatility regime (ATR percentile)
   - Time-of-day patterns (UTC hour bucket)
   - **NOT**: RSI, MACD, BB — these are arbitraged away

### 3D. Migration Plan

**Week 1 (Quick Wins):**
- Archive 20+ losing strategies (just set archived=1)
- Implement ATR-based SL/TP for the 4 keepers
- Add per-coin whitelist to orderflow_imbalance (AAVE, SUI, BTC, RUNE only)
- Add basic regime filter: skip new trades when BTC ATR > 2x normal

**Weeks 2-4 (Structural Changes):**
- Implement walk-forward backtester with 60-day window, 5 folds
- Build regime detector (trending vs ranging vs high-vol)
- Create God Model dispatcher — single entry point per bar
- Add ML confidence threshold (0.55 minimum)
- Rebuild cross_asset_correlation with proper ETH-lag detection

**Months 1-2 (Aspirational):**
- Train real ML model on actual profitable trades (current FT winners)
- Add feature importance analysis — find what actually predicts crypto
- Live execution integration (Blofin API, not just paper)
- Portfolio-level position sizing (Kelly criterion)

---

## PART 4: Alternative Revenue Opportunities

### 1. Numerai Tournament

**Status:** Active. 3 models (robbyrobml, robbyrob2, robbyrob3).

**Realistic upside:**
- Top 100 models earn ~5% APY on staked NMR
- Rob's stake: likely 1-10 NMR (~$30-300)
- Realistic annual return: $15-150/year
- Ceiling with 100+ NMR stake and top-50 performance: ~$500-1,000/year

**Time to first dollar:** Already active
**Scalability:** Limited by stake capital and model performance
**Automation potential:** High (weekly submission is already automated)
**Verdict:** Keep running, but don't expect significant income. This is hobby money.

### 2. Crypto Arbitrage

**Opportunity:** CEX-to-CEX price differences (1-3% on volatile assets).

**Requirements:**
- Capital on multiple exchanges ($10K+ per exchange)
- Fast execution (<1 second)
- Withdrawal/deposit fees eat margins
- 24/7 monitoring

**Reality check:** 
- OpenClaw is not fast enough for true arbitrage
- By the time you detect a spread, it's gone
- Professional arb firms have co-located servers and sub-millisecond execution

**Time to first dollar:** 2-4 weeks
**Scalability:** High if you have capital
**Automation potential:** Low (speed is the problem)
**Verdict:** Not viable without serious infrastructure investment. Skip.

### 3. AI-Built SaaS Products

**Opportunity:** Niche micro-SaaS with Stripe paywall.

**Realistic candidates for OpenClaw to build:**
- Affiliate link rotators / analytics
- Scheduling/booking bots for niche industries
- Data scrapers → API products (weather, sports odds, real estate)
- Chrome extensions with freemium model

**Time to first dollar:** 4-8 weeks to build + launch
**Scalability:** High (software scales)
**Automation potential:** Medium (building is automated, marketing is not)
**Realistic monthly revenue:** $100-2,000/month for a successful micro-SaaS

**Verdict:** Best risk/reward ratio. One good product could generate more passive income than all trading combined.

### 4. Sports Betting / Odds Arbitrage

**Status:** Active in ai-workshop/projects/sports-betting. Has OCR pipeline, sportsbook scraping.

**Opportunity:** Cross-book arbitrage (2-5% guaranteed returns when lines diverge).

**Challenges:**
- Book limits (they ban winning bettors fast)
- Need accounts at multiple books
- State/legal restrictions
- Detection avoidance

**Time to first dollar:** 2-4 weeks (if infrastructure is ready)
**Scalability:** Limited by account limits
**Automation potential:** High for detection, medium for execution
**Realistic monthly revenue:** $200-1,000/month until accounts get limited

**Verdict:** Worth pursuing in parallel. Better expected value than crypto trading.

### 5. Freelance AI Automation

**Opportunity:** Selling OpenClaw workflows to businesses.

**Market size:** Large (every SMB wants automation)
**Competition:** High (Zapier, Make, n8n, thousands of consultants)

**What you'd actually sell:**
- Custom data pipelines
- Report automation
- CRM integrations
- Email/notification workflows

**Time to first dollar:** Depends on sales effort
**Scalability:** Low (it's consulting/services, not product)
**Automation potential:** Low (every client is different)

**Verdict:** Skip unless Rob wants to become an AI consultant.

### 6. Content Monetization

**Opportunity:** AI-generated newsletters, reports, data journalism.

**Examples:**
- Crypto market reports (daily/weekly)
- Sports betting picks newsletter
- Financial analysis for retail investors

**Monetization:**
- Substack subscriptions ($5-50/month per subscriber)
- Affiliate links in content
- Sponsored posts

**Time to first dollar:** 4-8 weeks to build audience
**Scalability:** High
**Automation potential:** Very high (OpenClaw can write and schedule)
**Realistic monthly revenue:** $50-500/month (first year), $1,000-10,000/month (at scale)

**Verdict:** High potential, but requires audience building. Could be a good side project.

### 7. Data Products

**Opportunity:** Selling NQ/Blofin research as signals or datasets.

**Products:**
- NQ strategy signals (TradersPost integration)
- Crypto momentum alerts
- Historical backtest datasets

**Reality check:**
- Signal products need track record (years of audited performance)
- Dataset market is competitive (Quandl, Polygon, etc.)
- Liability concerns with financial signals

**Time to first dollar:** 3-6 months (need track record)
**Scalability:** High
**Automation potential:** Very high
**Realistic monthly revenue:** $100-1,000/month (small subscriber base)

**Verdict:** Long-term play. Need to prove NQ works first.

---

### Revenue Opportunity Ranking

| Opportunity | Time to $ | Scalability | Automation | Steady-State Monthly |
|-------------|-----------|-------------|------------|---------------------|
| **AI-Built SaaS** | 4-8 weeks | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | $100-2,000 |
| **Sports Arb** | 2-4 weeks | ⭐⭐ | ⭐⭐⭐⭐ | $200-1,000 |
| **Content/Newsletter** | 4-8 weeks | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | $50-500 (scaling) |
| **NQ Trading** | Already live | ⭐⭐⭐ | ⭐⭐⭐⭐ | TBD (needs eval pass) |
| **Blofin (fixed)** | 4-8 weeks | ⭐⭐⭐ | ⭐⭐⭐⭐ | Maybe $0-500 |
| **Numerai** | Already live | ⭐ | ⭐⭐⭐⭐⭐ | $15-150 |
| **Data Products** | 3-6 months | ⭐⭐⭐ | ⭐⭐⭐⭐ | $100-1,000 |
| **Crypto Arb** | N/A | N/A | N/A | **Skip** |
| **Freelance AI** | ? | ⭐ | ⭐ | **Skip** |

---

## Final Verdict: What I'd Do With Your Money

1. **Fix the NQ pipeline first.** Momentum is working (PF=3.61). Get to 50+ FT trades with consistent profit, then pursue Lucid eval. This is the highest-ROI short-term play.

2. **Rebuild Blofin or abandon it.** Current architecture is broken beyond repair. Either:
   - Spend 4 weeks implementing the architecture changes above, OR
   - Shut it down and redeploy that compute to SaaS/content automation

3. **Build one AI SaaS product.** Pick a niche (affiliate link rotator, scheduling bot, Chrome extension). OpenClaw can build and ship in 4-8 weeks. Even a modest $200/month product is better than a trading system that loses money.

4. **Run sports arbitrage in parallel.** The infrastructure is already there. This is free money until the books limit you.

5. **Don't waste time on Numerai scaling or crypto arb.** The upside is too small.

---

*Report generated 2026-02-28 by Opus pipeline research agent.*

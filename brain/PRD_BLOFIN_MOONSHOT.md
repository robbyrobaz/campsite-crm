# PRD: Blofin-Moonshot Pipeline
**Status:** DRAFT — Pending Rob's review  
**Date:** 2026-02-28  
**Repo:** `/home/rob/.openclaw/workspace/blofin-moonshot/` (new repo)  
**Runs:** In parallel with blofin-stack v1 (paper only, no shared infra)

---

## Problem

Blofin v1 fires high-frequency signals across 30+ strategies and 32 coins, trying to eke out 0.5–1% edges on every move. The BT/FT correlation is -0.099. It's not working at scale.

The alternative thesis: **crypto has a specific, recurring phenomenon where coins 2x–10x in days.** These moves are not random — they're driven by identifiable preconditions (volume spikes, social momentum, exchange listings, low market cap + high volatility regimes). If we can identify coins 24–72 hours *before* a 30%+ move, even a 20–30% win rate generates massive positive EV.

---

## Goal

Build a pipeline that answers one question: **"Which coins are about to make a 30%+ move in the next 1–7 days?"**

- Primary threshold: **30% move in 7 days** (open to tuning — research phase will find optimal)
- Signal type: **directional** (up only, or up+down with separate models)
- Instruments: Blofin paper account (same API), altcoins only (not BTC/ETH — too efficient)
- Mode: Paper trading first. Live only with Rob's explicit approval.

---

## Architecture

```
Data Layer
  ├── Price/volume history (Blofin API, all coins, 1h/4h/1d bars)
  ├── Market cap + coin age (CoinGecko API — free tier)
  ├── Social signals (optional phase 2: LunarCrush or Reddit/Twitter scrape)
  └── On-chain signals (optional phase 3: new listings, whale wallets)

Research Phase (Opus agent)
  ├── What features historically predict 30%+ moves?
  ├── What's the base rate? (how often does any coin do 30% in 7d?)
  ├── Which coin characteristics matter? (cap, age, volatility regime, volume)
  ├── Optimal threshold (30%? 50%? 1 week? 3 days?)
  └── Feature importance ranking

ML Phase
  ├── Label generation: did this coin move 30%+ in next N days?
  ├── Features: technical (ATR, RSI, BB, volume ratio), regime (trending/ranging),
  │            coin metadata (mcap, age, listing recency), momentum windows
  ├── Model: binary classifier (XGBoost/LightGBM) — predict P(big move in N days)
  ├── Validation: walk-forward (NO lookahead), OOS holdout
  └── Output: daily score per coin (0–1 probability)

Signal Engine
  ├── Daily scan: score all coins, rank by probability
  ├── Alert: top N coins crossing threshold (e.g. P > 0.65)
  ├── Entry: buy top-ranked coin at open next day
  ├── Exit: TP at 30% | SL at -10% | Time stop at 7 days
  └── Position sizing: equal weight, max 5 concurrent positions

Backtest
  ├── Walk-forward on 12 months of history
  ├── Metrics: hit rate (% of signals that hit 30%), avg gain when hit, PF
  ├── Benchmark: random coin selection (is our model better than chance?)
  └── Gate: hit rate > 25%, PF > 1.5

Forward Test
  ├── Paper trades on Blofin (same infra as v1 but separate DB)
  ├── Gate: 30 paper trades, hit rate > 20%, avg gain > 15%
  └── Duration: minimum 4 weeks before live consideration

Live (Rob approves separately)
  ├── Small capital ($100–500)
  ├── Same entry/exit rules
  └── Promoted pairs only (proven in FT)
```

---

## Research Questions (Opus Agent — Phase 1)

The Opus research agent should answer ALL of these before any code is written:

1. **Base rate:** In the Blofin universe (32 coins), how often does any coin make 30%+ in 7 days? Is the base rate high enough to build a strategy around? (If it's 2% of weeks, we can't build anything. If it's 15%, we can.)

2. **Optimal threshold:** Is 30%/7d the right target? Or should we use 20%/3d, 50%/14d, etc.? What threshold maximizes both frequency (enough samples) and magnitude (worth trading)?

3. **Best predictive features:** Which features have historically preceded big moves in crypto?
   - Volume: pre-move volume ratio (current vs 30d avg)
   - Volatility regime: low-vol compression before explosive moves (Bollinger squeeze)
   - Momentum: coin already up 10% in last 3 days (continuation) vs flat (breakout)
   - Market cap: do small caps (< $1B) have more big moves than large caps?
   - Coin age: newly listed coins vs mature coins — which pops more?
   - Cross-coin correlation: does BTC/ETH pumping predict altcoin pumps?

4. **Directional bias:** Are big moves predominantly bullish or is it worth modeling bearish too? (Shorting in bull markets = getting liquidated. Long-only may be right.)

5. **Coin universe:** Should we expand beyond the 32 Blofin coins? CoinGecko has 10,000+ coins. More coins = more samples. Tradeoff: liquidity, slippage, Blofin availability.

6. **False positive profile:** When the model fires and a big move DOESN'T happen, what does the coin do? (Flat? Small loss? Dumps hard?) This determines if a 10% SL is right or if we need tighter/looser stops.

7. **Timing:** Is day 1–3 after signal the highest expected value window, or is day 3–7 better?

8. **Data requirements:** How much historical data do we need per coin for a statistically valid backtest? CoinGecko free tier vs paid?

---

## Data Sources

| Source | Data | Cost | Notes |
|--------|------|------|-------|
| Blofin REST API | Price/volume, 32 coins, up to 1d bars | Free | Already have auth |
| CoinGecko API | Market cap, coin age, historical OHLCV, 10K+ coins | Free (50 req/min) | No key needed |
| LunarCrush (Phase 2) | Social volume, mentions, sentiment | $29/mo | Defer — research first |
| Blofin WebSocket | Real-time price | Free | Already integrated |

---

## Success Criteria

| Phase | Gate |
|-------|------|
| Research | Opus delivers: base rate, optimal threshold, top 5 features, go/no-go recommendation |
| Backtest | Hit rate > 25% on holdout, PF > 1.5, better than random baseline |
| Forward Test | 30 paper trades, hit rate > 20%, avg gain on winners > 15%, Max DD < 25% |
| Live | Rob's explicit approval only |

**Go/no-go decision after research:** If base rate is < 5% or Opus finds no predictive features, we kill the project before writing any code. Don't build for the sake of building.

---

## What Makes This Different From V1

| V1 | Moonshot |
|----|---------|
| 30+ strategies, high frequency | 1 model, low frequency (daily scan) |
| Fixed % SL/TP (0.65% SL) | ATR-based or % of target (10% SL, 30% TP) |
| No regime detection | Regime is a core input feature |
| BT-optimized (anti-predictive) | Labels are real outcomes, OOS validated |
| Fires 100+ signals/day | 1–5 signals/week maximum |
| Needs all 32 coins to "work" | Works if even 3–5 coins respond |

---

## Parallel Running Plan

- v1 continues unchanged — don't touch it
- Moonshot gets its own repo (`blofin-moonshot/`) and DB (`moonshot.db`)
- Separate paper trading account allocation (small, dedicated)
- Separate dashboard panel (add to master dashboard when FT starts)
- No shared code with v1 — clean slate

---

## Timeline

| Milestone | When |
|-----------|------|
| Opus research complete | 2–3 hours after card runs |
| Rob reviews research findings | Same day |
| Go/no-go decision | After review |
| Build data pipeline + labeling | Day 1 (if go) |
| Backtest + validation | Day 2–3 |
| Forward test start | Day 3–5 |
| Live decision | 4+ weeks of FT data |

---

## Constraints

- ⛔ No live trading without Rob's explicit approval
- ⛔ Paper only during FT phase
- Long-only initially (no shorting until we understand the move profile)
- Max 5 concurrent paper positions
- No leverage
- Opus agent for research only — Haiku for all builder/code tasks after

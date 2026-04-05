# 📊 Data Collection - What Gets Logged

## Overview

The system collects **comprehensive forward-testing data** to evaluate scoring effectiveness and optimize the strategy.

---

## Log Files (all in `logs/`)

### 1. `pumpfun_tokens.jsonl` - Raw Discovery Data
**What:** Every token discovered from Pump.fun API  
**When:** At discovery time (real-time)  
**Use:** Raw data archive, verify all tokens captured

**Schema:**
```json
{
  "contract": "ABC123...",
  "data": { /* full pump.fun API response */ },
  "timestamp": "2026-04-05T20:00:00Z"
}
```

---

### 2. `scored_tokens.jsonl` - Scoring Results
**What:** Every token scored by our system  
**When:** At discovery time  
**Use:** PRIMARY analysis file - does score predict outcomes?

**Schema:**
```json
{
  "contract": "ABC123...",
  "symbol": "TOKEN",
  "name": "Token Name",
  "score": 75.5,
  "details": {
    "speed": 25,              // Age score (0-30)
    "age_minutes": 15.3,
    "liquidity": 12,           // Liquidity score (0-15)
    "liquidity_usd": 15000,
    "engagement": 10,          // Engagement score (0-15)
    "reply_count": 25,
    "txns_1h": 150,
    "price_action": 15,        // Price score (0-20)
    "price_change_1h": 85.5,
    "buy_pressure": 8,         // Buy ratio score (0-10)
    "buy_ratio": 2.5,
    "multi_source": 10,        // Multi-source bonus (0-15)
    "sources": 2,
    "red_flags": ["BOOSTED_25"],
    "red_flag_penalty": -10
  },
  "twitter": "https://x.com/...",
  "telegram": "https://t.me/...",
  "created_timestamp": 1775417297000,
  "scored_timestamp": "2026-04-05T20:00:00Z"
}
```

**Analysis Questions:**
- Do high scores (>80) correlate with better outcomes?
- Which scoring factors matter most?
- What's the optimal entry threshold? (60? 70? 80?)

---

### 3. `token_tracking.jsonl` - Outcome Tracking
**What:** Ongoing tracking of every discovered token  
**When:** Updated at intervals (5min, 30min, 1hr, 6hr, 24hr)  
**Use:** Track how tokens evolve over time

**Schema:**
```json
{
  "contract": "ABC123...",
  "symbol": "TOKEN",
  "initial_score": 75.5,
  "discovered_at": "2026-04-05T20:00:00Z",
  "created_at": 1775417297000,
  "tracking_started": "2026-04-05T20:00:05Z",
  "snapshots": [
    {
      "age_minutes": 5.2,
      "interval": 5,
      "timestamp": "2026-04-05T20:05:00Z",
      "price_usd": 0.00001947,
      "market_cap": 25000,
      "liquidity_usd": 12500,
      "volume_24h": 15000,
      "volume_1h": 5000,
      "price_change_24h": 150,
      "price_change_1h": 85,
      "txns_24h_buys": 200,
      "txns_24h_sells": 75
    },
    // ... more snapshots at 30min, 1hr, 6hr, 24hr
  ],
  "status": "TRACKING"  // or "COMPLETED"
}
```

**Analysis Questions:**
- Did early price action (5min, 30min) predict final outcome?
- At what time interval is scoring most predictive?
- Do high-volume tokens in first hour perform better?

---

### 4. `token_outcomes.jsonl` - Final Outcomes
**What:** Final classification of every tracked token  
**When:** After 24hr or all snapshots complete  
**Use:** CRITICAL - ground truth for scoring evaluation

**Schema:**
```json
{
  "contract": "ABC123...",
  "symbol": "TOKEN",
  "initial_score": 75.5,
  "created_at": 1775417297000,
  "discovered_at": "2026-04-05T20:00:00Z",
  "tracking_completed": "2026-04-06T20:00:00Z",
  "age_at_completion": 1440.5,
  "snapshots": [ /* all snapshots */ ],
  "outcome": "WINNER",  // MOONED | WINNER | SMALL_WIN | FLAT | DUMPED | RUGGED
  "peak_market_cap": 150000,
  "final_market_cap": 85000,
  "final_liquidity": 45000
}
```

**Outcome Definitions:**
- `MOONED`: 10x+ peak market cap
- `WINNER`: 3-10x peak market cap
- `SMALL_WIN`: 1.5-3x peak
- `FLAT`: Neither pumped nor dumped significantly
- `DUMPED`: Down 70%+ from peak
- `RUGGED`: Lost 90%+ liquidity

**Analysis Questions:**
- Score 80-100: X% MOONED/WINNER
- Score 60-79: Y% MOONED/WINNER
- Score 40-59: Z% MOONED/WINNER
- **Which tier has best risk/reward?**

---

### 5. `paper_trades.jsonl` - Entry Log
**What:** Every paper trade entry  
**When:** When score ≥60 (Tier 2+)  
**Use:** Track what we actually entered

**Schema:**
```json
{
  "contract": "ABC123...",
  "symbol": "TOKEN",
  "tier": "TIER_2_HIGH",
  "score": 75.5,
  "entry_price_usd": 0.00001947,
  "position_size_usd": 10.0,
  "entry_timestamp": "2026-04-05T20:00:00Z",
  "stop_loss_pct": -30,
  "take_profit_levels": [50, 100, 200, 500, 1000],
  "status": "OPEN"
}
```

---

### 6. `open_positions.jsonl` - Position Updates
**What:** Updated position data (P&L, current price)  
**When:** Every 2 minutes (position monitor)  
**Use:** Track real-time P&L, partial exits

**Schema:**
```json
{
  "contract": "ABC123...",
  "symbol": "TOKEN",
  "tier": "TIER_2_HIGH",
  "score": 75.5,
  "entry_price_usd": 0.00001947,
  "current_price_usd": 0.00002920,
  "position_size_usd": 8.0,  // Reduced after partial exits
  "pnl_pct": 50.0,
  "pnl_usd": 4.0,
  "entry_timestamp": "2026-04-05T20:00:00Z",
  "last_checked": "2026-04-05T20:30:00Z",
  "take_profit_exits": [50],  // Already exited at +50%
  "status": "OPEN"  // or "CLOSED"
}
```

---

### 7. `exits.jsonl` - Exit Log
**What:** Every exit (partial or full)  
**When:** Stop loss hit or take profit triggered  
**Use:** Calculate win rate, average gain/loss

**Schema:**
```json
{
  "contract": "ABC123...",
  "symbol": "TOKEN",
  "entry_price": 0.00001947,
  "exit_price": 0.00002920,
  "position_size": 2.0,       // Size of THIS exit
  "pnl_pct": 50.0,
  "pnl_usd": 1.0,
  "reason": "TAKE_PROFIT (+50%)",  // or "STOP_LOSS (-30%)"
  "exit_pct": 20,             // Sold 20% of position
  "exit_timestamp": "2026-04-05T20:30:00Z",
  "entry_timestamp": "2026-04-05T20:00:00Z",
  "tier": "TIER_2_HIGH",
  "score": 75.5
}
```

**Analysis Questions:**
- Average hold time for winners vs losers?
- How many actually hit +500% or +1000%?
- Do we exit too early?

---

## Data Flow

```
┌─────────────────┐
│  Pump.fun API   │ → pumpfun_tokens.jsonl (raw)
└────────┬────────┘
         ↓
┌─────────────────┐
│  Score Token    │ → scored_tokens.jsonl (scores)
└────────┬────────┘
         ↓
    ┌────┴─────┐
    │          │
    ↓          ↓
┌────────┐  ┌──────────────┐
│ Enter? │  │ Track Token  │ → token_tracking.jsonl
└───┬────┘  │  Over Time   │
    │       └──────┬───────┘
    │              ↓
    │       ┌──────────────┐
    │       │ Final        │ → token_outcomes.jsonl ⭐
    │       │ Outcome      │
    │       └──────────────┘
    ↓
┌──────────────┐
│ paper_trades │ → paper_trades.jsonl
│   .jsonl     │
└──────┬───────┘
       ↓
┌──────────────┐
│ Monitor P&L  │ → open_positions.jsonl
│ Check Exits  │
└──────┬───────┘
       ↓
┌──────────────┐
│   exits      │ → exits.jsonl ⭐
│   .jsonl     │
└──────────────┘
```

---

## Analysis After 3-7 Days

### Primary Analysis: Score vs Outcome

```python
import json
import pandas as pd

# Load outcomes
outcomes = []
with open('logs/token_outcomes.jsonl') as f:
    for line in f:
        outcomes.append(json.loads(line))

df = pd.DataFrame(outcomes)

# Group by score tier
df['tier'] = pd.cut(df['initial_score'], 
                    bins=[0, 40, 60, 80, 100],
                    labels=['<40', '40-59', '60-79', '80-100'])

# Calculate win rates per tier
win_rates = df.groupby('tier')['outcome'].apply(
    lambda x: (x.isin(['MOONED', 'WINNER', 'SMALL_WIN'])).mean()
)

print(win_rates)

# Expected output:
# <40:     10-15% win rate
# 40-59:   20-30% win rate
# 60-79:   35-45% win rate  ← Our entry threshold
# 80-100:  50-60% win rate
```

### Secondary Analysis: What Factors Matter?

```python
# Load scored tokens with outcomes
scored = []
with open('logs/scored_tokens.jsonl') as f:
    for line in f:
        scored.append(json.loads(line))

outcomes_dict = {o['contract']: o['outcome'] for o in outcomes}

# Merge
for s in scored:
    s['outcome'] = outcomes_dict.get(s['contract'], 'UNKNOWN')

df = pd.DataFrame(scored)

# Correlation analysis
factors = ['speed', 'liquidity', 'engagement', 'price_action', 'buy_pressure', 'multi_source']

for factor in factors:
    df[factor] = df['details'].apply(lambda x: x.get(factor, 0))
    
# Which factor best predicts MOONED?
df['is_moon'] = df['outcome'] == 'MOONED'

for factor in factors:
    corr = df[[factor, 'is_moon']].corr().iloc[0, 1]
    print(f"{factor}: {corr:.3f}")

# Expected: multi_source and engagement will correlate highest
```

---

## What Makes Good Data?

**Minimum for useful analysis:**
- ✅ 100+ tokens tracked to completion (24hr)
- ✅ At least 10 entries (paper trades)
- ✅ Mix of outcomes (some winners, some rugs)
- ✅ Complete snapshots (all time intervals)

**Timeline:**
- **Day 1-2:** System collects data, mostly junk tokens
- **Day 3-4:** First completions (24hr outcomes)
- **Day 5-7:** Enough data for meaningful analysis

---

## Files Summary

| File | Purpose | Update Frequency | Analysis Priority |
|------|---------|------------------|-------------------|
| `pumpfun_tokens.jsonl` | Raw archive | Real-time | Low |
| `scored_tokens.jsonl` | Scoring data | Real-time | **HIGH** |
| `token_tracking.jsonl` | Time-series | 5min intervals | Medium |
| `token_outcomes.jsonl` | Ground truth | After 24hr | **CRITICAL** |
| `paper_trades.jsonl` | Entry log | When score ≥60 | **HIGH** |
| `open_positions.jsonl` | P&L tracking | Every 2min | Medium |
| `exits.jsonl` | Exit log | When hit | **HIGH** |

---

## Next Steps

**After 3 days:**
1. Check `token_outcomes.jsonl` - do we have 50+ completed?
2. Analyze score vs outcome correlation
3. Identify top predictive factors

**After 7 days:**
1. Full analysis (100+ outcomes)
2. Optimize scoring weights
3. Adjust entry threshold if needed
4. Deploy v2 with validated scoring

---

## Quick Checks

**Count completed outcomes:**
```bash
cat logs/token_outcomes.jsonl | wc -l
```

**Count by outcome type:**
```bash
cat logs/token_outcomes.jsonl | jq -r .outcome | sort | uniq -c
```

**Average score by outcome:**
```bash
cat logs/token_outcomes.jsonl | jq -s 'group_by(.outcome) | map({outcome: .[0].outcome, avg_score: (map(.initial_score) | add / length)})'
```

**Check paper trade performance:**
```bash
cat logs/exits.jsonl | jq -s 'map(.pnl_pct) | {avg: (add/length), min: min, max: max}'
```

---

**System is now collecting COMPREHENSIVE data for full evaluation! 🎯**

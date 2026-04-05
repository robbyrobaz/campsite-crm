# 🎯 Multi-Source Memecoin Trading Strategy

## Reality Check

**Baseline expectation:** 95% of new memecoins are losers (rugs, scams, dead)
**Our goal:** Find the 5% winners and let them run

**Current Telegram-only performance:**
- Win rate: 22%
- Entry timing: 2+ hours after launch
- Coverage: 188 contracts/day

**Target with multi-source:**
- **Win rate: 35-40%** (60-80% improvement)
- **Entry timing: 5-30 minutes** (6-24x faster)
- **Coverage: 500-1000 contracts/day** (2.7-5.3x more)

---

## The Three Data Sources

### 1. Pump.fun API (PRIMARY - Fastest)
**Speed:** Instant (0-30 seconds after creation)
**Coverage:** Every token created on pump.fun (~80% of Solana memecoins)

**Unique Data:**
- `created_timestamp` - Exact creation time
- `reply_count` - Real engagement (not bots!)
- `real_sol_reserves` - Actual liquidity (not virtual)
- `complete` - Graduated to Raydium? (bullish!)
- `is_banned` / `nsfw` - Filter garbage immediately
- `ath_market_cap` - Already pumped hard? (avoid)

**What it tells us:**
- ✅ Token exists
- ✅ Has real liquidity
- ✅ People are engaging with it
- ✅ Not banned/NSFW

### 2. Dexscreener API (VALIDATION - Analytics)
**Speed:** 2-5 minutes after pump.fun
**Coverage:** All DEXes (pump.fun, Raydium, Jupiter, etc.)

**Unique Data:**
- `txns.h1.buys` / `txns.h1.sells` - Transaction counts
- `volume.h1` - Actual trading volume
- `priceChange.h1` - Price movement %
- `boosts.active` - PAID PROMOTION (red flag!)
- `liquidity.usd` - USD liquidity value

**What it tells us:**
- ✅ Price is moving (not dead)
- ✅ People are buying (not just creating)
- ✅ Volume is real (not wash trading)
- ❌ Paid boost = possible shill (be cautious)

### 3. Telegram Channels (SOCIAL PROOF - Validation)
**Speed:** 30 min - 3 hours after creation
**Coverage:** Selective (only tokens people talk about)

**Unique Data:**
- Multiple channels mention it = real buzz
- Channel reputation (some channels better than others)
- Message sentiment (bullish/cautious)

**What it tells us:**
- ✅ Community interest (not just bot trading)
- ✅ Multi-channel = higher confidence
- ❌ Single channel only = possible coordinated shill

---

## The Funnel (Expect 95% to Fail!)

```
PUMP.FUN API
  ↓
  ├─ 1000 tokens/day created
  ├─ Filter: banned, NSFW, zero liquidity
  ├─ Filter: reply_count = 0 (no engagement)
  ├─ Filter: ATH already 100x (late to party)
  ↓
  └─ ~300 tokens pass (70% filtered)

DEXSCREENER VALIDATION (2-5 min later)
  ↓
  ├─ 300 tokens to check
  ├─ Filter: volume_1h < $100 (dead)
  ├─ Filter: txns < 10 (no activity)
  ├─ Filter: price_change_1h < -50% (dumping)
  ├─ Filter: boosts.active > 50 (heavy paid promo)
  ↓
  └─ ~100 tokens pass (67% filtered)

TELEGRAM CONFLUENCE (30min - 3hr later)
  ↓
  ├─ 100 tokens being tracked
  ├─ ~10-20 mentioned on Telegram
  ├─ Multi-channel mentions = highest confidence
  ↓
  └─ ~5-10 HIGH CONFIDENCE signals/day

EXPECTED OUTCOMES (from 10 high-confidence entries):
  ├─ 5 tokens: RUG/FAIL immediately (-100%) ❌
  ├─ 3 tokens: Small pump, dump, exit break-even or small loss ⚠️
  ├─ 2 tokens: WINNERS - 2x to 50x 🚀✅
  └─ NET: Profitable if we let winners run!
```

---

## Scoring System (0-100 points)

### Speed Score (0-30 points)
**Age matters - earlier = better**

```
Token age (from created_timestamp):
  < 5 min:    30 points  🔥 ULTRA EARLY
  5-15 min:   25 points  🔥 VERY EARLY
  15-30 min:  20 points  ⚡ EARLY
  30-60 min:  15 points  ✅ GOOD TIMING
  1-2 hours:  10 points  ⚠️  LATE
  > 2 hours:   5 points  ❌ TOO LATE
```

### Liquidity Score (0-15 points)
**Real liquidity = less rug risk**

```
Real SOL reserves (pump.fun) or USD liquidity (Dexscreener):
  > $50k:   15 points  ✅ SAFE
  $10-50k:  12 points  ✅ GOOD
  $5-10k:   10 points  ⚠️  RISKY
  $1-5k:     7 points  ⚠️  VERY RISKY
  $500-1k:   3 points  🚩 DANGER
  < $500:    0 points  ❌ AVOID
```

### Engagement Score (0-15 points)
**Real people = real demand**

```
Pump.fun reply_count + Dexscreener txns_1h:
  > 100 engaged: 15 points  🔥 VIRAL
  50-100:        12 points  ✅ STRONG
  20-50:         10 points  ✅ GOOD
  10-20:          7 points  ⚠️  WEAK
  5-10:           3 points  🚩 VERY WEAK
  < 5:            0 points  ❌ DEAD
```

### Price Action Score (0-20 points)
**Pumping = momentum**

```
Price change (1h from Dexscreener):
  > 100%:    20 points  🚀 MOONING
  50-100%:   15 points  ✅ PUMPING
  20-50%:    10 points  ✅ RISING
  0-20%:      5 points  ⚠️  FLAT
  -20-0%:     2 points  🚩 DUMPING
  < -20%:     0 points  ❌ RUG
```

### Buy Pressure Score (0-10 points)
**More buys than sells = bullish**

```
Buy/Sell ratio (from Dexscreener txns):
  > 3.0:      10 points  🔥 FOMO
  2.0-3.0:     8 points  ✅ STRONG
  1.5-2.0:     6 points  ✅ GOOD
  1.0-1.5:     4 points  ⚠️  BALANCED
  0.5-1.0:     2 points  🚩 SELLING PRESSURE
  < 0.5:       0 points  ❌ DUMPING
```

### Multi-Source Bonus (0-15 points)
**Confluence = confidence**

```
Sources mentioning the token:
  All 3 (Pump+Dex+Telegram):  +15 points  🔥 MAXIMUM CONFIDENCE
  2 sources (Pump+Dex):        +10 points  ✅ HIGH CONFIDENCE
  2 sources (Dex+Telegram):    +10 points  ✅ VALIDATED
  1 source only:                +0 points  ⚠️  UNCONFIRMED
  
  Multiple Telegram channels:   +5 points  ✅ SOCIAL PROOF
```

### Red Flags (SUBTRACT points)
**Avoid these**

```
  - Boosted on Dexscreener (>20 active): -10 points  🚩 PAID SHILL
  - NSFW flagged:                        -20 points  ❌ AVOID
  - Banned:                              -100 points ❌ SKIP
  - ATH market cap > 100x current:       -15 points  ⚠️  LATE TO PARTY
  - Creator has 0 followers/reputation:  -5 points   ⚠️  UNKNOWN
  - No social links:                     -10 points  🚩 SKETCHY
```

---

## Entry Tiers (Based on Total Score)

### TIER 1: 80-100 Points - MAXIMUM CONFIDENCE 🔥
**Entry:** Immediately
**Position size:** 3x normal ($15 per token if $5 base)
**Why:** All signals align, early timing, strong fundamentals

**Characteristics:**
- Age < 30 min
- 2-3 source confluence
- High engagement
- Strong buy pressure
- Good liquidity
- Pumping

**Expected:** 1-2 per day
**Win rate target:** 50-60%

---

### TIER 2: 60-79 Points - HIGH CONFIDENCE ✅
**Entry:** Immediately
**Position size:** 2x normal ($10 per token)
**Why:** Most signals positive, might be missing Telegram or slightly older

**Characteristics:**
- Age < 60 min
- 2 source confluence
- Good engagement
- Positive price action
- Adequate liquidity

**Expected:** 3-5 per day
**Win rate target:** 35-45%

---

### TIER 3: 40-59 Points - MEDIUM CONFIDENCE ⚠️
**Entry:** Watch for 5-10 minutes first
**Position size:** 1x normal ($5 per token)
**Why:** Some good signals but also some concerns

**Characteristics:**
- Age < 2 hours
- 1-2 sources
- Moderate engagement
- Mixed price action
- Lower liquidity

**Expected:** 5-10 per day
**Win rate target:** 20-30%

---

### TIER 4: < 40 Points - LOW CONFIDENCE ❌
**Entry:** Skip / Watch only
**Position size:** $0
**Why:** Not enough conviction

---

## Exit Strategy (CRITICAL - Let Winners Run!)

### Stop Loss (Cut Losers Fast)
```
From entry price:
  -30% = EXIT IMMEDIATELY  (token is dead/rug)
  -50% = FORCE EXIT        (system override)
```

**Why:** Memecoins dump to zero fast. If it's down 30%, it's not coming back.

### Take Profit (Let Winners Run!)
```
This is where we make money - DON'T exit early!

  +50%:   Sell 20% (get 20% of entry back, free ride the rest)
  +100%:  Sell 20% (lock in some profit)
  +200%:  Sell 20% (lock in more profit)
  +500%:  Sell 20% (getting serious)
  +1000%: Sell 20% (final exit)

Remaining 20% = MOON BAG (hold forever or until rug)
```

**Why:** Winners can go 10x, 50x, 100x. Early exit = missed gains.

**Rob's directive (Mar 15):** "FT is FREE. Expect 95% losers. Only track top performers."
This means: Small losses on many, BIG WINS on few = net profitable.

### Trailing Stop (Protect Gains)
```
Once +100%:  Set trailing stop at -40% from peak
Once +500%:  Set trailing stop at -50% from peak
Once +1000%: Set trailing stop at -60% from peak

Example:
  Entry: $0.00001
  Pumps to: $0.0001 (+900%)
  Trailing stop: -50% from peak = $0.00005
  If it dumps to $0.00005, exit with +400% gain instead of riding back to zero
```

---

## Daily Workflow (Automated)

### Every 30 Seconds:
1. **Poll Pump.fun API** for new tokens
2. **Score immediately** (age, liquidity, engagement, red flags)
3. **Flag high scores** (>60 points from pump.fun data alone)

### Every 2 Minutes:
4. **Check Dexscreener** for flagged tokens
5. **Add price action data** (txns, volume, price change, buy ratio)
6. **Recalculate score** with full data
7. **Log to high_confidence.jsonl** if score >60

### Every 5 Minutes:
8. **Check Telegram scanner** logs
9. **Match contracts** between all sources
10. **Add multi-source bonus** to scores
11. **Generate entry signals** for Tier 1 & 2

### Every 30 Minutes:
12. **Review open positions**
13. **Update trailing stops**
14. **Exit if stop loss hit**
15. **Take partial profits** per schedule

---

## Expected Daily Performance

**With full multi-source system:**

```
INPUT:
  - ~1000 new tokens/day created on pump.fun
  - ~300 pass initial filters
  - ~100 pass Dexscreener validation
  - ~10-15 are high-confidence (Tier 1 & 2)

ENTER 10-15 POSITIONS/DAY:
  - 8-10 tokens FAIL (-30% stop loss) = -$40 to -$50 loss
  - 2-3 tokens break even or small loss = -$5 loss
  - 1-2 tokens WIN BIG (+200% to +1000%) = +$100 to +$500 gain

NET PER DAY: +$45 to +$445
NET PER WEEK: +$315 to +$3,115
NET PER MONTH: +$1,350 to +$13,350

Starting balance: $98.05 (live Kalshi account)
After 1 month: $1,448 to $13,448  (15x to 137x)
```

**Key insight:** We don't need high win rate. We need to:
1. **Cut losers fast** (-30% max loss)
2. **Let winners run** (+500% to +1000% gains)
3. **Enter early** (30-60 min timing = better prices)

---

## Risk Management

### Position Sizing
- **Base position:** $5 per token
- **Tier 1 (80-100 score):** $15 per token (3x)
- **Tier 2 (60-79 score):** $10 per token (2x)
- **Tier 3 (40-59 score):** $5 per token (1x)

**Max daily risk:** 10-15 positions × $5-15 = $50-225/day

### Stop Loss Discipline
- **NEVER override stop loss**
- **-30% = exit, no exceptions**
- **System enforced** (not manual)

### Let Winners Run
- **Don't exit early** (biggest mistake!)
- **Scale out slowly** (20% at each level)
- **Keep 20% moon bag** (capture extreme outliers)

---

## Implementation Priority

### Phase 1: Build Multi-Source Scanner (TODAY - 2 hours)
- Pump.fun API poller (every 30 sec)
- Dexscreener validator (2 min delay)
- Telegram matcher (5 min check)
- Combined scoring system
- High-confidence signal logger

### Phase 2: Integrate with Paper Trading (TOMORROW - 3 hours)
- Read high_confidence.jsonl signals
- Auto-enter Tier 1 & 2 (>60 score)
- Implement stop loss logic (-30%)
- Implement take profit schedule
- Implement trailing stops

### Phase 3: Collect Data & Optimize (WEEK 1)
- Run paper trading for 7 days
- Track actual win rate per tier
- Adjust scoring weights
- Tune entry/exit thresholds

### Phase 4: Deploy to Live (WEEK 2)
- If paper trading profitable
- Start with 50% of target position sizes
- Scale up over 2 weeks

---

## Success Metrics

### Week 1 (Paper Trading):
- ✅ Catching 10-15 high-confidence signals/day
- ✅ Entry timing < 60 min average
- ✅ Multi-source confluence on 30%+ of entries
- ✅ System running stable (no crashes)

### Week 2-3 (Paper Trading):
- ✅ Win rate > 25% (better than current 22%)
- ✅ Average winner > 3x average loser
- ✅ Positive P&L overall
- ✅ Scoring system working (high scores = better performance)

### Week 4+ (Live):
- ✅ Win rate 35-40%
- ✅ Monthly return > 300%
- ✅ Letting winners run to +500%+
- ✅ Cutting losers at -30% max

---

## Files & Structure

```
~/.openclaw/workspace/dexscreener-scanner/
├── MASTER_STRATEGY.md           ← THIS FILE
├── API_DATA_COMPARISON.md       ← Data source breakdown
│
├── scanner_pumpfun.py           ← Pump.fun API poller
├── scanner_dexscreener.py       ← Dexscreener validator
├── scanner_combined.py          ← Multi-source scorer
│
├── logs/
│   ├── pumpfun_raw.jsonl       ← All pump.fun tokens
│   ├── dexscreener_validated.jsonl  ← Dex data added
│   ├── high_confidence.jsonl   ← Tier 1 & 2 signals
│   └── telegram_matched.jsonl  ← Multi-source confluence
│
└── backtest/
    └── scoring_analysis.py      ← Test scoring on historical data
```

---

## The Bottom Line

**Current state:** Telegram-only, 22% win rate, 2+ hour delay, 188 contracts/day
**Target state:** Multi-source, 35-40% win rate, 5-30 min entry, 1000+ contracts/day

**Strategy:** Cast wide net → Filter aggressively → Enter early → Cut losers fast → Let winners run

**Reality:** 95% will fail. That's expected. The 5% winners going 10x-100x = where we make money.

**Next step:** Build the combined scanner. Want me to do it now?

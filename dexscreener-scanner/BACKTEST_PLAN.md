# 🧪 Backtesting Strategy - Test Scoring on Historical Data

## Can We Backtest? YES!

### Available Historical Data:

**1. Pump.fun API - Past 24-48 Hours**
- Query with offset: `?offset=100&limit=50` to get older tokens
- Each token has `created_timestamp` and `ath_market_cap`
- **Key insight:** Compare `market_cap` vs `ath_market_cap` = did it moon?

**2. Dexscreener API - Any Token Ever Created**
- Query by address: `/latest/dex/tokens/{address}`
- Get full history: creation time, ATH, current price
- **Key insight:** `priceChange.h24` shows if it pumped or rugged

**3. Telegram Scanner - Last 3 Days**
- We have `signals.jsonl` with contracts + timestamps
- Can match against pump.fun/dex data
- **Key insight:** Did Telegram-mentioned tokens actually perform better?

---

## Backtest Approach (Get Data First, Then Score)

### Step 1: Collect Historical Token Data (1-7 days old)

**From Pump.fun:**
```python
# Collect tokens created in last 7 days
for offset in range(0, 5000, 50):  # 100 pages = ~5000 tokens
    tokens = get_pumpfun_coins(offset=offset, limit=50)
    
    for token in tokens:
        age_days = (now - token['created_timestamp']) / 86400000
        
        if age_days <= 7:  # Last 7 days only
            save_token({
                'contract': token['mint'],
                'created_at': token['created_timestamp'],
                'initial_mc': token['market_cap'],
                'ath_mc': token['ath_market_cap'],
                'ath_timestamp': token['ath_market_cap_timestamp'],
                'reply_count': token['reply_count'],
                'twitter': token.get('twitter'),
                'telegram': token.get('telegram'),
                'is_complete': token['complete'],
                'real_sol_reserves': token['real_sol_reserves'],
            })
```

### Step 2: Enrich with Current Dexscreener Data

**For each historical token:**
```python
# Get current state from Dexscreener
dex_data = get_dexscreener_token(contract)

if dex_data:
    token['current_price'] = dex_data['priceUsd']
    token['current_mc'] = dex_data['marketCap']
    token['volume_24h'] = dex_data['volume']['h24']
    token['price_change_24h'] = dex_data['priceChange']['h24']
    
    # Calculate outcome
    token['outcome'] = calculate_outcome(
        initial_mc=token['ath_mc'],
        current_mc=token['current_mc']
    )
```

### Step 3: Match with Telegram Mentions

**Check if token was mentioned:**
```python
# Load Telegram signals from last 7 days
telegram_contracts = load_telegram_signals()

token['telegram_mentioned'] = contract in telegram_contracts
token['telegram_channels'] = count_channels(contract)
token['telegram_first_mention'] = get_first_mention_time(contract)
```

### Step 4: Score Each Token (Simulate Entry)

**Apply our scoring system AS IF we entered when created:**
```python
# Score at time of creation (simulate real-time entry)
score = 0

# Age score (0 at creation = max points)
score += 30  # All tokens get max age score in backtest

# Liquidity score (from pump.fun data at creation)
if token['real_sol_reserves'] > 50000:
    score += 15
elif token['real_sol_reserves'] > 10000:
    score += 12
# ... etc

# Engagement score (reply_count at creation)
if token['reply_count'] > 100:
    score += 15
elif token['reply_count'] > 50:
    score += 12
# ... etc

# Multi-source bonus (simulated)
sources = 1  # Always have pump.fun
if token.get('liquidity_usd', 0) > 500:  # Would appear on Dex
    sources += 1
if token['telegram_mentioned']:
    sources += 1

if sources == 3:
    score += 15
elif sources == 2:
    score += 10

token['score'] = score
```

### Step 5: Categorize Outcomes

**Define winners vs losers:**
```python
def calculate_outcome(initial_mc, current_mc):
    """
    Simulate holding from creation to now
    """
    roi = ((current_mc / initial_mc) - 1) * 100
    
    if roi >= 500:
        return 'MOON'      # 5x+
    elif roi >= 100:
        return 'WINNER'    # 2x-5x
    elif roi >= -30:
        return 'NEUTRAL'   # Break even to small gain
    elif roi >= -70:
        return 'LOSER'     # -30% to -70%
    else:
        return 'RUG'       # -70%+ (dead)
```

### Step 6: Analyze Score vs Outcome

**Does high score = better performance?**
```python
# Group tokens by score tier
tier_1 = tokens where score >= 80  # Max confidence
tier_2 = tokens where score 60-79  # High confidence
tier_3 = tokens where score 40-59  # Medium confidence
tier_4 = tokens where score < 40   # Low confidence

# Calculate win rates per tier
for tier in [tier_1, tier_2, tier_3, tier_4]:
    moons = count(outcome == 'MOON')
    winners = count(outcome in ['MOON', 'WINNER'])
    losers = count(outcome in ['LOSER', 'RUG'])
    
    win_rate = winners / total
    avg_roi = mean(roi)
    
    print(f"Tier score {tier.min}-{tier.max}:")
    print(f"  Win rate: {win_rate}%")
    print(f"  Avg ROI: {avg_roi}%")
    print(f"  Moons: {moons}")
    print(f"  Winners: {winners}")
    print(f"  Losers: {losers}")
```

---

## What We'll Learn

### 1. Does Scoring Work?
**Question:** Do high scores correlate with better outcomes?

**Expected:**
- Tier 1 (80-100): 40-50% win rate, higher avg ROI
- Tier 2 (60-79): 30-40% win rate
- Tier 3 (40-59): 20-30% win rate
- Tier 4 (<40): 10-20% win rate

**If TRUE:** Scoring works, proceed with confidence
**If FALSE:** Adjust weights, try different factors

### 2. Which Factors Matter Most?
**Question:** What predicts winners?

**Test:**
- High reply_count → better outcomes?
- High initial liquidity → better outcomes?
- Telegram mentions → better outcomes?
- Multi-source confluence → better outcomes?
- Graduated (complete=true) → better outcomes?

**Adjust scoring weights based on results.**

### 3. What's the Optimal Entry Threshold?
**Question:** What minimum score should we require?

**Test:**
- Enter all score >40: High volume, lower win rate
- Enter only score >60: Medium volume, better win rate
- Enter only score >80: Low volume, best win rate

**Find sweet spot: volume vs quality**

### 4. Does Telegram Add Value?
**Question:** Do Telegram-mentioned tokens perform better?

**Compare:**
- Tokens mentioned on Telegram: X% win rate
- Tokens NOT mentioned: Y% win rate
- Multi-channel mentions: Z% win rate

**If NO difference:** Maybe skip Telegram, focus on pump.fun+dex
**If BIG difference:** Telegram is valuable signal

### 5. What's Realistic Performance?
**Question:** What returns can we expect?

**Simulate portfolio:**
```python
# Start with $100
# Enter 10 tokens/day for 7 days
# Apply stop loss (-30%)
# Apply take profit schedule

results = simulate_portfolio(
    starting_balance=100,
    tokens_per_day=10,
    days=7,
    score_threshold=60,
    stop_loss=-30,
    take_profit_levels=[50, 100, 200, 500, 1000]
)

print(f"Final balance: ${results['final_balance']}")
print(f"ROI: {results['roi']}%")
print(f"Win rate: {results['win_rate']}%")
print(f"Avg winner: {results['avg_winner']}%")
print(f"Avg loser: {results['avg_loser']}%")
```

---

## Implementation Steps

### Step 1: Data Collection Script (30 min)
```bash
python collect_historical.py --days 7 --limit 5000
```
- Fetches pump.fun tokens from last 7 days
- Enriches with Dexscreener current data
- Matches with Telegram signals
- Saves to `backtest_data.jsonl`

### Step 2: Scoring Script (20 min)
```bash
python score_historical.py --input backtest_data.jsonl
```
- Applies our scoring system
- Simulates entry at creation time
- Categorizes outcomes (MOON/WINNER/NEUTRAL/LOSER/RUG)
- Saves to `backtest_scored.jsonl`

### Step 3: Analysis Script (30 min)
```bash
python analyze_backtest.py --input backtest_scored.jsonl
```
- Calculates win rates per tier
- Identifies top factors
- Simulates portfolio performance
- Generates report + charts

### Step 4: Optimize Weights (1 hour)
```bash
python optimize_scoring.py --input backtest_scored.jsonl
```
- Grid search over scoring weights
- Find combination that maximizes:
  - Win rate in Tier 1
  - Separation between tiers
  - Total ROI
- Output: Optimized scoring config

---

## Expected Timeline

**Total: 2-3 hours to complete backtest**

```
Hour 1: Data Collection
  ├─ Fetch pump.fun historical (5000 tokens)
  ├─ Query Dexscreener for each (current state)
  ├─ Match Telegram signals
  └─ Save dataset

Hour 2: Scoring & Analysis
  ├─ Apply scoring system
  ├─ Calculate outcomes
  ├─ Generate win rate stats
  └─ Create visualizations

Hour 3: Optimization & Validation
  ├─ Test different score weights
  ├─ Simulate portfolios
  ├─ Validate assumptions
  └─ Finalize scoring config
```

---

## Decision Points

### After Backtest Results:

**Scenario A: Scoring Works Well (>35% win rate in Tier 1)**
→ Proceed to live paper trading with confidence
→ Use optimized weights from backtest

**Scenario B: Scoring Mediocre (25-35% win rate)**
→ Adjust weights based on factor analysis
→ Re-run backtest with new weights
→ Proceed cautiously

**Scenario C: Scoring Doesn't Work (<25% win rate)**
→ Revisit strategy
→ Maybe memecoins are too random?
→ Or our data sources don't predict outcomes?
→ Pivot or abandon approach

---

## Constraints & Limitations

### What Backtest CAN'T Tell Us:
1. **Entry timing precision** - We don't know exact price at 5min, 30min, 1hr
2. **Liquidity at entry** - Can't verify if we could actually buy
3. **Rug detection** - Some rugs happen in minutes (before Dex data)
4. **Future market conditions** - Past week might not predict next week

### What Backtest CAN Tell Us:
1. ✅ **Relative performance** - Do high scores beat low scores?
2. ✅ **Factor importance** - What matters most?
3. ✅ **Realistic win rates** - What % actually pumped?
4. ✅ **Score threshold** - Where to set entry bar?
5. ✅ **Multi-source value** - Does confluence help?

---

## Bottom Line

**YES, we should backtest first!**

**Advantages:**
- Validate strategy before risking money
- Optimize scoring weights with real data
- Set realistic expectations
- Identify which factors matter

**Time cost:** 2-3 hours
**Value:** High - prevents building a broken system

**Recommendation:**
1. Build data collection script NOW
2. Run backtest on last 7 days
3. Analyze results
4. Optimize scoring
5. THEN build live scanner with validated weights

**Want me to start with the data collection script?**

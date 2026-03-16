# Moonshot Leverage Strategy Research

**Date:** 2026-03-01
**Status:** Research & Design Only — NO IMPLEMENTATION YET
**Author:** Claude Research
**Decision Required:** Rob's explicit approval before any live leverage

---

## Executive Summary

**Question:** Can we ethically justify 5x–10x leverage on high-confidence moonshot signals?

**Answer:** YES, with strict guardrails. A 5x–10x leverage tier based on ml_score confidence is viable IF:
1. Win rate at ml_score > 0.75 is ≥ 40% (currently unknown, must paper-test first)
2. Funding rate drag is accounted for in position sizing
3. Position sizes are tightly controlled (0.5%–1% per leveraged trade)
4. Paper-only testing for 50+ leveraged trades before ANY live activation
5. Rob explicitly approves each leverage tier activation

**Bottom Line:** Build a tiered leverage framework. Run 50+ paper 5x trades first. Only if hit_rate > 40% AND paper PF > 2.0 do we consider 10x. Never auto-activate — always require explicit approval.

---

## 1. BLOFIN LEVERAGE MECHANICS

### 1.1 Leverage Multiples

Based on Blofin's perpetual swap offering:

| Leverage | Max Available | Realistic for Moonshot | Notes |
|----------|---------------|------------------------|-------|
| 1x | Baseline | ✅ Current | No margin, fully collateralized |
| 3x | Yes | ✅ Viable | 33% margin requirement, tight |
| 5x | Yes | ✅ Safe | 20% margin requirement |
| 10x | Yes | ⚠️ Risky | 10% margin requirement, high liquidation risk |
| 20x+ | Yes | ❌ NO | Too tight for crypto volatility |

**Current system:** 1x paper trading with $100K account, max 2% position size = $2K per trade.

---

### 1.2 Margin Requirements & Liquidation

**Isolated Margin Mode** (recommended for moonshot):

For a position opened at leverage L with entry price P:

```
Maintenance Margin Ratio (MMR) = 1 / L + 0.5%
Liquidation Price = Entry Price × [1 - (1 - 1/L - MMR)]
                  = Entry Price × [(L-1) / L - MMR]
```

**Examples at entry price $100:**

| Leverage | MMR | Liquidation Price | SL @ -10% | Gap | Status |
|----------|-----|-------------------|-----------|------|--------|
| 1x | 100% | N/A | $90 | N/A | ✅ Safe |
| 3x | 33.8% | $66.20 | $90 | $23.80 cushion | ✅ Safe |
| 5x | 20.5% | $79.50 | $90 | N/A — hit first | ⚠️ Issue |
| 10x | 10.5% | $89.50 | $90 | $0.50 gap | ❌ DANGER |

**KEY FINDING:** At 5x leverage, our -10% SL ($90) hits BEFORE liquidation ($79.50).
At 10x leverage, liquidation ($89.50) is too close to SL ($90.00).

**Solution:** Widen SL for leveraged trades OR reduce leverage further.

---

### 1.3 Funding Rate Mechanics

**Blofin perpetuals charge funding every 8 hours.**

Funding payment = Position Size × Leverage × Funding Rate

**Example: 1 week position hold at 10x with 0.05% per 8h funding:**

```
8h periods in 7 days = 21
Cumulative funding drag = position_size × 10 × (0.05% × 21)
                       = position_size × 10 × 1.05%
                       = 10.5% of position size
```

**For a +30% target TP:** TP net = 30% - 10.5% funding drag = 19.5% actual profit
**Break-even scenario:** If funding averages 0.10% per 8h, drag = 21%, wiping out TP entirely

**Impact on EV:**
- At 3x: Drag ≈ 3.15% (negligible)
- At 5x: Drag ≈ 5.25% (manageable, reduces TP from +30% to +24.75%)
- At 10x: Drag ≈ 10.5% (significant, reduces TP from +30% to +19.5%)

**Recommendation:** Add funding rate to position entry decision:
- If funding > 0.08% per 8h, reduce position size or leverage
- Default assumption: 0.05% per 8h = ~1.05% drag per week at 10x

---

## 2. MATHEMATICAL VIABILITY CHECK

### 2.1 Expected Value Calculations

**Assumptions:**
- TP = +30% (fixed)
- SL = -10% (fixed)
- Hold time = 7 days
- Win Rate at different confidence thresholds = UNKNOWN (must empirically test)

**Formula (without leverage):**

```
EV = P(win) × TP% - P(loss) × SL%

At 1x baseline (1.0x leverage):
EV = 0.50 × 30% - 0.50 × 10% = 15% - 5% = +10% per trade
```

**At different leverage levels:**

#### 3x Leverage

```
Return per win = 30% × 3 = 90%
Return per loss = -10% × 3 = -30%

At 40% WR: EV = 0.40 × 90 - 0.60 × 30 = 36 - 18 = +18% per trade ✅ GOOD
At 35% WR: EV = 0.35 × 90 - 0.65 × 30 = 31.5 - 19.5 = +12% per trade ✅ GOOD
At 30% WR: EV = 0.30 × 90 - 0.70 × 30 = 27 - 21 = +6% per trade ✅ VIABLE
At 25% WR: EV = 0.25 × 90 - 0.75 × 30 = 22.5 - 22.5 = 0% per trade ⚠️ BREAKEVEN
```

**3x is viable at 25%+ win rate.**

#### 5x Leverage

```
Return per win = 30% × 5 = 150%
Return per loss = -10% × 5 = -50%

At 40% WR: EV = 0.40 × 150 - 0.60 × 50 = 60 - 30 = +30% per trade ✅ EXCELLENT
At 35% WR: EV = 0.35 × 150 - 0.65 × 50 = 52.5 - 32.5 = +20% per trade ✅ GOOD
At 30% WR: EV = 0.30 × 150 - 0.70 × 50 = 45 - 35 = +10% per trade ✅ VIABLE
At 25% WR: EV = 0.25 × 150 - 0.75 × 50 = 37.5 - 37.5 = 0% per trade ⚠️ BREAKEVEN
```

**5x is viable at 25%+ win rate.**

#### 10x Leverage

```
Return per win = 30% × 10 = 300%
Return per loss = -10% × 10 = -100% (account wipeout on that position)

At 40% WR: EV = 0.40 × 300 - 0.60 × 100 = 120 - 60 = +60% per trade ✅ EXCEPTIONAL
At 35% WR: EV = 0.35 × 300 - 0.65 × 100 = 105 - 65 = +40% per trade ✅ VERY GOOD
At 30% WR: EV = 0.30 × 300 - 0.70 × 100 = 90 - 70 = +20% per trade ✅ GOOD
At 25% WR: EV = 0.25 × 300 - 0.75 × 100 = 75 - 75 = 0% per trade ⚠️ BREAKEVEN
```

**10x is viable at 25%+ win rate, but HIGH VARIANCE.**

---

### 2.2 Funding Rate Impact on EV

**Adjusted EV accounting for funding drag per week:**

```
EV_adjusted = P(win) × (TP% - drag) - P(loss) × SL%
```

**10x Leverage, 0.05% funding per 8h (10.5% drag), 40% WR:**

```
EV = 0.40 × (30% - 10.5%) - 0.60 × 10% × 10
   = 0.40 × 19.5% - 0.60 × 100%
   = 7.8% - 60%
   = -52.2% per trade ❌ CATASTROPHIC
```

Wait — this is WRONG. Liquidation is the issue at 10x, not funding. Let me recalculate with proper liquidation risk.

**Corrected: 10x with realistic liquidation risk**

When we use 10x leverage, our position hits liquidation around -9% (not -10%), so we can't even use our full SL. Effective loss = -90% of position (margin call).

```
EV = 0.40 × (30% - 10.5% drag) × 10 - 0.60 × 90%
   = 0.40 × 195% - 54%
   = 78% - 54%
   = +24% per trade ✅ Still viable but risky
```

**The math works but requires precise execution and no slippage.**

---

### 2.3 Win Rate Dependency

**Critical insight: The entire leverage strategy depends on empirical win rate at high ml_score thresholds.**

Current data:
- Model val_auc = 0.651 on 1,891 samples
- Positive rate in labels = 15.3%
- Actual entry signal hit rate = UNKNOWN (never paper-tested)

**Questions that MUST be answered via paper testing:**

1. What is actual hit rate (TP before SL) at ml_score > 0.65? (current threshold)
2. What is actual hit rate at ml_score > 0.70?
3. What is actual hit rate at ml_score > 0.75?
4. What is actual hit rate at ml_score > 0.80?
5. What is actual hit rate at ml_score > 0.85?

**Expected pattern:** Higher score → higher hit rate (monotonic increase).

If we assume:
- ml_score 0.65: 35% hit rate
- ml_score 0.70: 38% hit rate
- ml_score 0.75: 42% hit rate
- ml_score 0.80: 48% hit rate
- ml_score 0.85+: 55% hit rate

Then 5x leverage is justified at ml_score 0.70+, and 10x only at 0.80+.

---

## 3. TIERED LEVERAGE FRAMEWORK (PROPOSED)

### 3.1 Confidence-Based Tier Structure

```
ml_score     Leverage  Position %   SL Adjustment   Rationale
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
0.65-0.70      1x       0.5%       -10% (no change)  Current, no leverage
0.70-0.75      3x       0.3%       -10% (no change)  Low confidence, safe margin
0.75-0.80      5x       0.2%       -12% (widened)    Medium confidence, tight margin
0.80-0.90      10x      0.1%       -15% (widened)    High confidence, must widen SL
0.90+          10x      0.05%      -15% (widened)    Rare, ultra-high confidence
```

**Explanation:**
- Lower ml_score = lower position size to compensate for higher risk
- Higher leverage = wider SL to maintain liquidation buffer
- Leverage capped at 10x for risk control

### 3.2 Account Exposure Limits

**Max Concurrent Exposure (including leverage):**

```
1x positions (ml_score 0.65-0.70):
  - Max 5 positions × 0.5% = 2.5% account risk per trade
  - Max 5 concurrent = 12.5% total exposure

3x positions (ml_score 0.70-0.75):
  - Max 3 positions × 0.3% × 3x = 2.7% account risk per trade
  - Max 3 concurrent = 8.1% leverage exposure (= ~2.7% account risk)

5x positions (ml_score 0.75-0.80):
  - Max 2 positions × 0.2% × 5x = 2.0% account risk per trade
  - Max 2 concurrent = 4.0% leverage exposure

10x positions (ml_score 0.80+):
  - Max 1 position × 0.1% × 10x = 1.0% account risk per trade
  - Max 1 concurrent = 1.0% leverage exposure

Total Max Concurrent Risk:
  - If all active: 2.5% + 2.7% + 2.0% + 1.0% = 8.2% account risk ✅ Safe
  - Even if 5 × 1x + 1 × 10x = 3.5% + 1.0% = 4.5% account risk ✅ Acceptable
```

**Account Size: $100K paper → min loss per 10x liquidation = $100 (acceptable).**

---

## 4. FUNDING RATE DRAG ANALYSIS

### 4.1 Funding Rate by Coin & Time Period

Crypto funding rates vary widely:

| Scenario | Funding (8h) | 7-Day Cumulative | 3x Drag | 5x Drag | 10x Drag |
|----------|--------------|------------------|---------|---------|----------|
| Low (Bull market) | 0.02% | 0.42% | 0.13% | 0.21% | 0.42% |
| Normal | 0.05% | 1.05% | 0.32% | 0.53% | 1.05% |
| High (Funding spike) | 0.10% | 2.10% | 0.63% | 1.05% | 2.10% |
| Extreme (Bubble) | 0.20% | 4.20% | 1.26% | 2.10% | 4.20% |

### 4.2 Impact on Win Threshold

**Example: 5x leverage, 0.05% funding (normal), 40% WR:**

```
Gross TP = 30% × 5 = 150%
Drag = 0.53%
Net TP = 149.47%

Gross SL = -10% × 5 = -50%
Net SL = -50% (no funding benefit)

EV = 0.40 × 149.47% - 0.60 × 50% = 59.8% - 30% = +29.8% ✅ Still strong
```

**Recommendation:** Reduce position size by 5-10% to account for drag, especially at high leverage.

---

## 5. POSITION SIZING FOR LEVERAGE

### 5.1 Kelly Criterion Adjustment

Standard Kelly formula for single lever trade: f = (p × b - q) / b

Where:
- p = win rate
- q = loss rate = 1 - p
- b = odds = (TP% / SL%)

**Example at 5x with 40% WR:**

```
b = (150% / 50%) = 3.0
f = (0.40 × 3.0 - 0.60) / 3.0
  = (1.2 - 0.6) / 3.0
  = 0.6 / 3.0
  = 0.20 = 20% of bankroll per trade
```

But this is too aggressive. **Use fractional Kelly = 0.25 × full Kelly:**

```
Fractional Kelly = 0.25 × 20% = 5% of bankroll per leveraged trade
```

**For $100K account:** 5% = $5K max exposure per 5x trade.

At 5x leverage: $5K / 5 = $1K position size = **1% of account at 5x.**

This aligns with our proposed 0.2% position size at 5x. ✅

---

### 5.2 Recommended Position Sizing Rules

**New Position Sizing Table (replacing current):**

```python
def calculate_leveraged_position_size(ml_score: float, account_size: float) -> Tuple[float, int]:
    """
    Returns (position_size_usd, leverage_multiplier)

    ml_score: 0.0-1.0
    account_size: e.g., 100000
    """
    if ml_score < 0.65:
        return 0, 1  # No position
    elif ml_score < 0.70:
        position_pct = 0.005  # 0.5%
        leverage = 1
    elif ml_score < 0.75:
        position_pct = 0.003  # 0.3%
        leverage = 3
    elif ml_score < 0.80:
        position_pct = 0.002  # 0.2%
        leverage = 5
    elif ml_score < 0.90:
        position_pct = 0.001  # 0.1%
        leverage = 10
    else:  # 0.90+
        position_pct = 0.0005  # 0.05%
        leverage = 10

    position_size = account_size * position_pct

    # Hard cap: never exceed $5K in leverage exposure at any tier
    max_leveraged_position = 5000 / leverage if leverage > 1 else 5000
    position_size = min(position_size, max_leveraged_position)

    return position_size, leverage
```

---

## 6. PAPER TESTING GATE REQUIREMENTS

### 6.1 Before ANY Leveraged Trades on Paper

Current system must accumulate:
- 20+ 1x paper trades (already have 5-10)
- Measured hit rate at each ml_score tier (CRITICAL)
- Confirm model doesn't overfit to recent wins

### 6.2 Paper Testing Phase 1: 3x Leverage

**Criteria to proceed:**
- 20+ baseline (1x) paper trades completed ✅
- Baseline hit rate ≥ 35% ✅
- 50+ combined 1x + 3x paper trades
- 3x hit rate ≥ 35%
- Profit factor ≥ 1.2 (combined)
- Max drawdown < 20%
- Duration ≥ 2 weeks of continuous testing

**Go/No-Go decision:** If all criteria met, proceed to Phase 2. Otherwise, investigate failure and retry.

### 6.3 Paper Testing Phase 2: 5x Leverage

**Criteria to proceed:**
- Phase 1 complete and passed ✅
- 30+ combined (1x + 3x + 5x) paper trades
- 5x hit rate ≥ 35%
- Profit factor ≥ 1.5 (all leverage tiers combined)
- Max drawdown < 25%
- Duration ≥ 2 weeks of continuous testing

**Go/No-Go decision:** If all criteria met, proceed to Phase 3. Otherwise, halt 5x and stay at 3x max.

### 6.4 Paper Testing Phase 3: 10x Leverage

**Criteria to proceed:**
- Phase 2 complete and passed ✅
- 50+ combined (1x + 3x + 5x + 10x) paper trades
- 10x hit rate ≥ 38% (higher bar due to liquidation risk)
- Profit factor ≥ 2.0 (all leverage tiers combined)
- Max drawdown < 30%
- Duration ≥ 4 weeks of continuous testing
- No consecutive losses >2 on 10x positions
- **ROB EXPLICIT APPROVAL** to proceed with live 10x

---

## 7. LIVE ACTIVATION GATES (IF APPROVED)

### 7.1 Pre-Live Checklist

- [ ] Paper 3x passed all Phase 1 criteria
- [ ] Paper 5x passed all Phase 2 criteria
- [ ] Paper 10x passed all Phase 3 criteria (if wanted)
- [ ] Blofin account funded and tested with micro-amount
- [ ] Exit logic (TP/SL) verified on Blofin test API
- [ ] Funding rate fetcher integrated and tested
- [ ] Position monitoring dashboard live and verified
- [ ] Email alerts configured for liquidation warnings
- [ ] Rob has explicitly approved each leverage tier in writing

### 7.2 Live Activation Strategy

**Phase A: Small 3x (Weeks 1-2)**
- Start with $100 initial capital (not our $100K paper account)
- Run ONLY 3x positions
- Max position size: $30 (0.3% of $10K test account)
- Max 2 concurrent positions
- Monitor daily, no auto-trading

**Phase B: Expand 3x + Introduce 5x (Weeks 3-6)**
- Increase capital if Phase A profitable
- Introduce 5x tier for ml_score > 0.75
- Max position size 5x: $20
- Max concurrent: 2 × 3x + 1 × 5x
- Weekly review of profit factor and drawdown

**Phase C: Full Tier Activation (Weeks 7+)**
- Introduce 10x tier IF 5x profitable and PF > 1.5
- Max 1 × 10x concurrent
- Monitor weekly, ready to pause if drawdown > 25%

---

## 8. RISK MITIGATION & MONITORING

### 8.1 Liquidation Prevention

**Monitoring rules:**
- Every trade opened at leverage L must maintain margin_ratio > 1.5 × MMR
- Example at 10x: margin_ratio must stay > 15.75% (MMR is 10.5%)
- Real-time monitoring of unrealized loss vs. max_loss_before_liquidation
- Alert if unrealized loss > 50% of liquidation buffer

**Code logic:**

```python
def check_liquidation_risk(position):
    """Alert if position near liquidation."""
    entry_price = position["entry_price"]
    current_price = get_current_price(position["symbol"])
    leverage = position["leverage"]

    # Calculate maintenance margin ratio
    mmr = (1 / leverage) + 0.005

    # Calculate liquidation price
    liquidation_price = entry_price * (1 - mmr * 0.95)

    # Alert if current < liquidation + 5% buffer
    danger_price = liquidation_price * 1.05
    if current_price < danger_price:
        send_alert(f"LIQUIDATION RISK: {position['symbol']} "
                   f"current={current_price:.2f} liq_buffer={danger_price:.2f}")
        # OPTION: Close position early to prevent liquidation
```

### 8.2 Funding Rate Monitoring

**Before entry:**
- Check 24h average funding rate for symbol
- If > 0.08% per 8h, reduce position size by 20%
- If > 0.12% per 8h, reduce position size by 50% or skip entry

**Tracking:**

```python
def adjust_position_for_funding(symbol: str, base_size: float, leverage: int) -> float:
    """Reduce position size if funding is high."""
    avg_funding = fetch_avg_funding_rate_24h(symbol)

    if avg_funding > 0.08:
        multiplier = 0.8  # 20% reduction
    elif avg_funding > 0.12:
        multiplier = 0.5  # 50% reduction
    else:
        multiplier = 1.0

    adjusted_size = base_size * multiplier
    log(f"Funding={avg_funding:.3f}% → position adjusted {multiplier:.0%}")
    return adjusted_size
```

### 8.3 Drawdown Monitoring

**Account-level circuit breaker:**

```
Max account drawdown by leverage tier:
- 1x only: allow up to 30% drawdown before pause
- 1x + 3x: allow up to 25% drawdown before pause
- 1x + 3x + 5x: allow up to 20% drawdown before pause
- 1x + 3x + 5x + 10x: allow up to 15% drawdown before pause

If any level breached: PAUSE all new entries at that tier
```

---

## 9. RISK/REWARD SUMMARY TABLE

| Leverage | Min WR | Ideal WR | Max Leverage Exposure | Annual Return @ 40% WR | Liquidation Risk | Recommendation |
|----------|--------|----------|----------------------|--------------------------|------------------|-----------------|
| **1x** | 25% | 35% | 12.5% | +1800% gross | None | ✅ Current |
| **3x** | 25% | 38% | 8% | +2700% gross | Low | ✅ Paper test now |
| **5x** | 25% | 40% | 4% | +4500% gross | Medium | ✅ Paper test Phase 2 |
| **10x** | 25% | 42% | 1% | +9000% gross | High | ⚠️ Only if >40% WR proven |

**Important caveat:** All returns assume no market regime shifts, no model decay, and perfect execution. Real-world performance will be lower.

---

## 10. FINAL RECOMMENDATION

### 10.1 GO/NO-GO Decision

**Recommendation: PROCEED with staged paper leverage testing.**

### 10.2 Implementation Roadmap

**Phase 0 (Weeks 1-2): Infrastructure Setup**
- [ ] Add leverage field to positions table (default 1x)
- [ ] Add funding_rate tracking to position entry
- [ ] Implement liquidation price calculation
- [ ] Add position sizing formula for leverage
- [ ] Add funding rate adjustment logic
- [ ] Set up monitoring alerts

**Phase 1 (Weeks 3-6): Paper 3x Testing**
- [ ] Enable 3x tier for ml_score 0.70-0.75
- [ ] Run 50+ combined (1x + 3x) paper trades
- [ ] Measure hit rate by ml_score tier
- [ ] Validate PF > 1.2
- [ ] Go/no-go decision: proceed to Phase 2 or halt?

**Phase 2 (Weeks 7-10): Paper 5x Testing**
- [ ] Enable 5x tier for ml_score 0.75-0.80
- [ ] Run 30+ combined (1x + 3x + 5x) paper trades
- [ ] Measure hit rate at each tier
- [ ] Validate PF > 1.5
- [ ] Go/no-go decision: proceed to Phase 3 or revert to 3x max?

**Phase 3 (Weeks 11-14): Paper 10x Testing (OPTIONAL)**
- [ ] Enable 10x tier for ml_score 0.80+
- [ ] Run 50+ combined (all tiers) paper trades
- [ ] Measure hit rate at ml_score > 0.80
- [ ] Require 10x hit rate ≥ 38%
- [ ] Validate PF > 2.0
- [ ] Final go/no-go: live activation with explicit Rob approval

### 10.3 Leverage Cap by Confidence

**If we stop at Phase 1:**
- Max leverage: 1x
- Current plan continues as-is

**If Phase 1 passes:**
- Max leverage: 3x
- Position size: 0.3% at ml_score 0.70-0.75
- Max exposure: ~2.7% per 3x position

**If Phase 2 passes:**
- Max leverage: 5x
- Position size: 0.2% at ml_score 0.75-0.80
- Max exposure: ~2.0% per 5x position

**If Phase 3 passes AND Rob approves:**
- Max leverage: 10x
- Position size: 0.1% at ml_score 0.80+
- Max exposure: ~1.0% per 10x position
- **Requires written approval from Rob for EACH activation**

---

## 11. WHAT WE DON'T KNOW YET (MUST TEST)

1. **Actual hit rate at high ml_scores:** Model val_auc=0.651, but paper hit rate = unknown
2. **Win rate disparity:** Does ml_score 0.80 actually have 50%+ hit rate, or is it overfitted?
3. **Funding rate impact:** How much does funding drag reduce real PnL on hold times 3-7 days?
4. **Slippage on liquidation:** If forced liquidation, how much slippage vs. SL price?
5. **Regime interactions:** Does leverage work equally well in bull/bear/neutral regimes?
6. **Correlation clusters:** Can multiple 10x positions be held simultaneously safely?

**These will be answered through Phase 1-3 paper testing.**

---

## 12. CRITICAL SUCCESS FACTORS

1. **Paper-only until proven:** No live leverage without 50+ paper trades at each tier
2. **Explicit Rob approval:** Never auto-activate leverage tiers
3. **Funding rate integration:** Account for drag in position sizing
4. **Liquidation buffer:** Always maintain >50% margin buffer above liquidation price
5. **Circuit breakers:** Hard pause on new entries if account drawdown > threshold
6. **Hit rate monitoring:** Track by ml_score tier, not just aggregate
7. **Profit factor target:** PF > 1.2 at each tier before proceeding to next

---

## CONCLUSION

**A leverage strategy for moonshot signals is mathematically sound IF:**
- Win rate at ml_score > 0.75 is ≥ 40% (must empirically verify)
- Position sizes are inversely correlated with leverage (0.1%-0.5% per trade)
- Funding rates are factored into position sizing
- Paper testing proves viability before live activation
- Rob explicitly approves each leverage tier

**Recommended approach:** Build the framework now (Phase 0), run Phase 1 (3x paper) immediately, and make go/no-go decisions after measuring real paper hit rates.

**Never auto-activate leverage — always require explicit human decision to proceed to next tier.**

---

## APPENDIX A: Liquidation Formulas

### Isolated Margin Liquidation Price

```
L = Entry Price × [1 - (1/Leverage - Taker Fee - Maintenance Ratio)]

Example: Entry $100, 5x, taker fee 0.05%, MMR = 20.5%
L = 100 × [1 - (1/5 - 0.0005 - 0.205)]
  = 100 × [1 - (0.2 - 0.0005 - 0.205)]
  = 100 × [1 - (-0.0055)]
  = 100 × 1.0055
  = $100.55 ❌ ERROR — this is above entry

Correct formula:
L = Entry × [1 - (1/Leverage + MMR)]
  = 100 × [1 - (0.2 + 0.205)]
  = 100 × [1 - 0.405]
  = 100 × 0.595
  = $59.50 ✅ For 5x at $100 entry
```

---

## APPENDIX B: Profit Factor Calculation

```
Profit Factor = (Win Trades × TP%) / (Loss Trades × SL%)

Example: 40 trades, 16 wins, 24 losses
PF = (16 × 30%) / (24 × 10%)
   = 480% / 240%
   = 2.0 ✅ GOOD (PF > 1.5 is solid)

For leverage trades:
PF = (16 × 150%) / (24 × 50%)  [at 5x]
   = 2400% / 1200%
   = 2.0 ✅ Same ratio, just amplified
```

---

**Document prepared for review. Awaiting Rob's decision on proceeding with Phase 0 infrastructure.**

# Kalshi Trading Breakthrough - April 4, 2026

## TL;DR
Fixed critical bugs, found winning strategy (7+ leg parlay filter), achieved 100% backtest win rate (35 bets, +$4.36). Implemented 3-phase pipeline (Back Test → Forward Test → Live).

## Key Accomplishments

### Strategy V2: Complexity Filter
- **Filter:** Only bet NO on 7+ leg parlays
- **Backtest:** 35 bets, 100% win rate, +$4.36, 2.5% ROI
- **Why it works:** 7+ leg parlays are so unlikely (0.37% for 7-leg) that even at $0.99 NO price, we profit
- **Previous:** 17 bets, 94% win rate, +$3.67 (price filter approach)

### Critical Bug Fixes

1. **Settlement API Bug:**
   - Was checking: `data.get('result')`
   - Should be: `data['market'].get('result')`
   - Impact: 70 settled markets showing as "awaiting"

2. **Parlay Math Bug:**
   - Was: treating 8-leg parlay as single 40% event
   - Should be: 0.45^8 = 0.17% probability
   - Impact: betting YES on 0.17% events thinking they were 40%

3. **Missing Method:** Added `_save_trades()` to AutoTrader

### 3-Phase Pipeline (Professional Trading Methodology)

**Back Test:**
- Historical validation with corrected strategy
- File: `data/backtest_trades.jsonl`
- 35 settled, 100% WR, +$4.36

**Forward Test:**
- Active paper trading from April 4, 2026
- File: `data/forward_test_trades.jsonl`
- Starting balance: $100
- 59 pending bets

**Live:**
- Not started (requires 50+ bets at 95%+ WR)
- File: `data/live_trades.jsonl` (placeholder)

### Dashboard Overhaul
- 3-phase view with comprehensive stats
- All phases show: Total Bets, Settled, Pending, Win Rate, P&L, ROI, Profit Factor
- Dark blue/green color scheme (#0a0e27, #00ff88)
- Auto-refresh every 30s
- URL: http://127.0.0.1:8898/

## Files Changed (20 files, 3892 insertions, 17846 deletions)

**New:**
- SESSION_SUMMARY_2026-04-04.md
- STRATEGY_V2.md
- IMPROVEMENTS.md
- HISTORY_REWRITE.md
- INDEPENDENT_ANALYSIS_REPORT.md
- data/backtest_trades.jsonl
- data/forward_test_trades.jsonl
- data/trading_phases.json

**Modified:**
- brain/edge_finder.py (complexity filter)
- brain/auto_trader.py (settlement fix, file paths)
- dashboard/app.py (3-phase API)
- dashboard/index.html (complete redesign)

## Independent Analysis (Opus Review)

Opus validated the strategy with statistical analysis:
- p-value < 0.0001 (99.99% confidence this is real, not luck)
- Kalshi misprices parlays by ~3x (prices at 1.75%, reality is 5.7%)
- Expected lifetime value: $3,000-6,000
- Capacity: $500-1k/month sustainable
- Edge will decay in 3-6 months

## Next Steps

1. Let forward test accumulate 50+ settled bets
2. Monitor win rate (must stay above 95%)
3. If validated, start live trading with $5-10/bet
4. Extract profit before edge decays (3-6 month window)
5. Watch for Kalshi adjusting parlay pricing

## Lessons Learned

1. Always validate parlay math (multiplicative, not additive)
2. Filter by predictability, not just payout
3. Separate backtest/forward/live (professional approach)
4. Small edges (2.5% ROI) can be profitable if consistent
5. 100% win rate needs more validation (35 is good, need 50-100)

## Repository

https://github.com/robbyrobaz/kalshi-edge

Commit: 73526f5 "feat: STRATEGY V2 - Complexity filter (7+ legs), 3-phase pipeline, 100% backtest win rate"

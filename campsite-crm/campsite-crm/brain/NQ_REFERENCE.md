# NQ Pipeline Reference

## equal_tops_bottoms — REHABILITATED (Feb 26 2026)
Was wrongly blacklisted with "PF 0.68 no edge" — that eval was broken. Actual WF data:
10/10 folds pass prop sim, PF 2.78–3.27, Sharpe 7.34–8.62, ~2000+ OOS trades/fold. Unblacklisted.
Pattern: tweezer tops/bottoms (ICT equal highs/lows) on 5-min NQ. Rob sees this in live trading.
ML feature research card dispatched to find best entry conditions + add as God Model expert #7.

## Definitive Phase 2 Leaderboard (All Filters Corrected)
1. momentum: PF 2.91, Sharpe 7.68, Calmar 808, ~9 trades/day
1. orb: PF 2.92, Sharpe 7.59, ~3 trades/day  ← TIED #1 (target_horizon=10, confirmed Feb 25)
3. gap_fill: PF 2.10, Sharpe 5.56, ~5.6 trades/day
4. vwap_fade: PF 2.08, Sharpe 5.56, ~8.6 trades/day
5. prev_day: PF 2.03, Sharpe 5.33, ~0.84 trades/day
6. vol_contraction: PF 1.86, Sharpe 4.70, ~4.1 trades/day
All 6 pass Lucid gates. Phase 3 Tier 1: momentum + orb.
ORB improvement: target_horizon 5→10 bars = +14.6% PF, +14.6% Sharpe, +2.9pp WR. 10/10 folds pass Lucid sim.

## NQ Filter Inflation Bug (Fixed)
- `_CANDIDATE_CFG` in `run_phase2.py` was overriding `max_trades_per_session=100` for all strategies
- gap_fill: 49K → 6.9K signals after fix (+25% PF)
- momentum: 18K → 7.5K signals (+2.4% PF)
- Any new strategy must have correct session cap in `_CANDIDATE_CFG`, not 100

## ML Exit God-Model — Key Findings
- Dominant feature: `pnl_drawdown_from_peak` at 73% — model IS a trailing stop
- Failed to improve PF on test period (losing regime for all strategies)
- Better alternative: ATR trailing stop (simpler, same behavior)
- Code is in `pipeline/exit_ml_engine.py` + `strategies/exit_ml_strategy.py` for future reference

## NQ Forward Test State (Feb 26)
- run_id=`smb_live_forward_test`, 129 trades
- momentum: +$5,900 ✅ | vol_contraction: +$160 ✅
- gapfill: 14% WR, -$2,565 ❌ | vwapfade: 11% WR, -$2,750 ❌
- equal_tops_bottoms (PF 3.02, best strategy) NOT YET in live inference — high priority
- Feb 26: 100 trades in one day — possible overtrading under investigation

## Execution Details
- Lucid 100K Flex eval: max DD $3K, daily DD $2K, min 10 trades
- Top Phase 2 strategies ready: momentum PF 2.91, orb PF 2.92 (target_horizon=10), gap_fill PF 2.43
- TradersPost webhook fires: {ticker: "NQH6", action: "buy"/"sell"/"exit", signalPrice: float, stopLoss: {...}, takeProfit: {...}}
- Tradovate execution NOT through TradersPost for data — only for order routing on prop accounts

## Tradovate Credentials (needed for live feed — not yet provided)
- `TRADOVATE_CID`  — integer, from tradovate.com → Settings → Developer → API Keys
- `TRADOVATE_SEC`  — string, same location
- `TRADOVATE_USER` — Tradovate email
- `TRADOVATE_PASS` — Tradovate password
- Store in: `NQ-Trading-PIPELINE/config_live.py` (gitignored)
- Current live data feed is SMB (NinjaTrader) — Tradovate feed is optional future upgrade

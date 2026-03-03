# MOONSHOT_SYNTHESIS.md
## 72-Hour Synthesis — Blofin Moonshot Decisions & Current State

**Generated:** 2026-03-02 ~18:57 MST  
**Full audit:** `/home/rob/.openclaw/workspace/blofin-moonshot/MOONSHOT_AUDIT.md` (branch `moonshot-audit-20260302`)

---

## TL;DR for Jarvis

The Moonshot system had two critical bugs that were both fixed in commits ~10 minutes before this audit ran (Mar 2, 18:40-18:47 MST, Opus-authored). The fixes are in the code but the next cycle to validate them runs at ~20:03 MST tonight.

**Watch that cycle carefully.**

---

## Key Decisions Rob Made (last 72h)

| Date | Decision | Quote |
|------|----------|-------|
| Feb 28 | Moonshot = persistent engine, not a scanner | "we are making a long term engine, just just a scan of the top candidates tonight" |
| Feb 28 | 342 coins, no static lists | "why do we think blofin only has 32 coins, that's just what you limited it too" |
| Feb 28 | Zero CoinGecko or external providers | "revert any changes that do anything with coingecko" |
| Feb 28 | Path-dependent labels (Opus recommendation approved) | SL before TP = loss, naive "did price hit +30%" = broken |
| Feb 28 | 2-4 year historical backfill | "For a rare-event model, you want to see the 2021 bull run, 2022 crash" |
| Feb 28 | Regime detection via BTC 30d return | Simple proxy, not overengineered |
| Feb 28 | Dashboard = model monitoring, not just coin PnL | "it's about model performance too" |
| Mar 2 | AUC is WRONG for champion selection | commit eae3864: "PF is profit, AUC means nothing" |

---

## Critical Bug History

### Bug 1: AUC-Based Champion Selection (FIXED — commit eae3864, Mar 2 18:40 MST)

`trainer.py` was comparing challengers to the champion using `val_auc`. Now uses `backtest_pf` from DB. 

Fix: `_load_champion_auc()` deprecated → `_load_champion_pf()` queries `model_versions.backtest_pf WHERE is_champion=1`.

### Bug 2: INVALIDATION Crash (FIXED — commit 2734995, Mar 2 18:46 MST) [UNTESTED IN LIVE CYCLE]

On Mar 2 at 19:16-19:17 UTC, 15 open profitable positions (avg +4.76% PnL) were all force-closed via INVALIDATION in 32 seconds. Root cause: `exit.py` called `model.predict_proba(features, side=direction)` without `symbol/ts_ms`, so regime features defaulted to 0.0, crashing ML scores to 0.129.

Fix: Line 145 now passes `symbol=symbol, ts_ms=int(time.time() * 1000)`.

**The fix is committed but has not been exercised in a cycle yet. Next cycle at ~20:03 MST.**

---

## Current DB State (as of 18:57 MST)

### tournament_models
- **62 backtest** models, avg bt_pf=12.1
- **15 forward_test** models, all `ft_trades=0` — tournament CANNOT crown a champion
- **0 champion** models (tournament has never crowned anyone)

### model_versions champions (what actually drives scoring)
- Long: version_id=6, bt_pf=**27.0**, 200 trades, val_auc=0.955 (trained Mar 1 01:19) ⚠️ suspicious high PF
- Short: version_id=18, bt_pf=16.1, 1,102 trades, val_auc=0.763 (trained Mar 1 10:36)

### positions
- 18 closed, avg PnL **+3.12%** (17 INVALIDATION, 1 manual test)
- 1 open: ETC-USDT long @ $8.77, entry 2026-03-02 16:04

---

## Architecture Gaps (NOT YET FIXED)

1. **Tournament FT tracking disconnected** — `tournament_models.ft_trades` stays at 0 because positions aren't linked to `tournament_models.model_id`. Tournament can't select a champion until this is wired.

2. **Two champion systems don't talk to each other** — `model_versions` (trainer.py, AUC then PF-based) vs `tournament_models` (competition-based, currently empty). Scoring uses `model_versions`. These systems need to merge.

3. **Overfitted current champions** — bt_pf=27.0 with 200 trades is a major red flag. May explain the INVALIDATION crash — the model is brittle, outputting extreme scores that fall apart when features change.

4. **`moonshot_scorer.py` status unknown** — Appears to be an older parallel scorer with its own position opening logic. If both `run_cycle.py` and `moonshot_scorer.py` are active, positions could double-enter.

---

## Things To Never Do Again

1. **AUC for champion selection** — Use `backtest_pf` only
2. **Promote regime-aware models without testing exit path** — The exit.py must be able to augment the same features used at entry
3. **Kill ML training processes in crons** — Ever. Even if they've been running 2 hours.
4. **Backfill without verifying depth** — Check actual row counts and date range after the run
5. **Static coin lists** — Everything via Blofin API, dynamic
6. **CoinGecko or external data** — Blofin-native only

---

## Recommended Next Steps (in priority order)

1. Watch the ~20:03 MST cycle — does ETC-USDT stay open with a valid ML score? That validates the INVALIDATION fix.
2. Investigate if `moonshot_scorer.py` is still running alongside `run_cycle.py`
3. Wire `tournament_models.ft_trades` updates — positions opened by scoring need to link back to a `model_id` for tournament scoring to work
4. Retrain champions with path-dependent labels + larger dataset
5. Validate long champion bt_pf=27.0 isn't in-sample overfitting

---

*Full details: `/home/rob/.openclaw/workspace/blofin-moonshot/MOONSHOT_AUDIT.md` on branch `moonshot-audit-20260302`*

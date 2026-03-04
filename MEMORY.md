# MEMORY.md — Learnings & Reference

> Project status lives in `brain/PROJECTS.md`. This file is for lessons learned, preferences, and reference info only.
> Detailed NQ data → `brain/NQ_REFERENCE.md`. Credentials/cameras/Tesla → `brain/CREDENTIALS_REFERENCE.md`.

## Architecture Reference

### Blofin Stack — Per-Coin Strategy (Key Design Decision, Feb 25 2026)
**Do NOT build per-coin ML models.** Global models stay trained on all coins.
**The right approach:** Use FT performance data to find which coin+strategy pairs respond well. Enable only those pairs.
- `strategy_coin_performance` — 32 coins × 26 strategies, BT + FT metrics per pair
- `strategy_coin_eligibility` — 1,112 rows, live per-coin performance with blacklist
- Pipeline fix (Feb 25): ensures good per-coin BT results flow through to FT promotion

**Dashboard rule:** NEVER show aggregate/system-wide PF, WR, or PnL. Always show **Top 10 pairs by FT profit factor** (min 20 FT trades).

### Blofin Stack
- Feature library: 95+ technical indicators
- Backtester: 7-day historical replay, multi-timeframe
- ML pipeline: 5 models (direction, risk, price, momentum, volatility)
- Ranking: `bt_pnl_pct` (compounded PnL %). Promotion: min 100 trades, PF≥1.35, MDD<50%, PnL>0. FT demotion: PF<1.1 or MDD>50% after 20 FT trades.
- Paper trading reality gap: slippage 0.052%/side (2.6x worse than assumed), fill rate 67%, stops too tight

### Numerai
- 3 models: robbyrobml, robbyrob2, robbyrob3
- API keys in `.env` in numerai-tournament/
- Era-boosting: 300 trees × 4 rounds, fixed tree count
- v2_equivalent (304 features) — full dataset (740 features) OOMs on 32GB RAM

### Model Routing (Updated Mar 2 2026)
- Subscription: Claude Max 20x ($200/mo flat). 7-day Sonnet limit is the binding constraint.
- **Current routing:** Sonnet primary for main Jarvis session. Haiku for all builders/crons.
- Gateway config: `~/.openclaw/openclaw.json` → `.agents.defaults.model.primary`
- **Opus is BANNED** — never let it back in. Rob was very angry about silent Opus usage.

### Three Pipelines Philosophy (Core Architecture)
**NQ Pipeline, Blofin v1, and Blofin Moonshot are THREE INDEPENDENT ARENAS.** Never combine outputs.
- **NQ Pipeline:** Top 2-3 strategies with FT PF ≥ 2.5 → God Model
- **Blofin v1:** Strategy+coin pairs with FT PF ≥ 1.35 → dynamic leverage tiers
- **Blofin Moonshot:** Coins with ml_score confidence ≥ 0.7 + FT validation

**Key insight:** Overall/aggregate performance is meaningless. The top 5 performers are gold. Always filter to top performers FIRST.

## Moonshot v2 Architecture (2026-03-02)

### What is it
Persistent engine finding big moves (±30%) on any of 343 Blofin USDT pairs.
- **Repo:** https://github.com/robbyrobaz/blofin-moonshot-v2
- **Dashboard:** port 8893
- **Timers:** moonshot-v2.timer (4h cycle), moonshot-v2-social.timer (1h social)

### Non-negotiables
- Champion selection = best FT PnL with ≥20 trades. NEVER AUC.
- One `compute_features()` function used for training, live scoring, AND exit (prevents INVALIDATION crash class)
- Path-dependent labels: hit +30% BEFORE -10% (long), hit -30% BEFORE +10% (short)
- All 343 pairs dynamic — no static coin lists, ever
- 100% Blofin-native data + free social (Fear & Greed, CoinGecko trending, RSS, Reddit, GitHub)
- Backtest gate: bt_pf ≥ 2.0, precision ≥ 40%, trades ≥ 50, ALL 3 walk-forward folds pass
- Bootstrap CI on PF: lower bound ≥ 1.0

### Why v1 died
Entry/exit used different feature sets when a regime-aware model was promoted. Exit called predict_proba() without symbol/ts_ms → regime features defaulted to 0.0 → all scores 0.129 → 15 profitable positions killed. v2 prevents this with feature_version hashing.

## Lessons Learned

- **Subagents die on heavy data tasks.** Multi-GB parquet loads → run in main session, not builders.
- **Builders die silently.** Always check sessions_list after spawn.
- **Claude rate limits are per-minute** (1000 RPM), not per billing window.
- **Volume column in Blofin ticks is tick count, not real volume.** Thresholds need ≤0.8 multiplier.
- **Agent Teams need interactive mode** — no `-p` flag. Must accept permissions prompt (option 2).
- **Git LFS rejects >2GB objects** — exclude large data files from backup sweeps.
- **pandas dropna() breaks index alignment with numpy.** Always `reset_index(drop=True)` after dropna.
- **Kanban discipline**: spawn → PATCH In Progress → update status.json — must happen atomically.
- **Dispatch immediately**: don't wait for "ideal conditions" — when data supports a test, run it.

## Rob's Preferences
- Concise updates, not walls of text
- Tell him what you did, not what you're about to do
- Lead with bad news
- Hates: babysitting AI, temp files in repos, being asked questions he already answered
- Wants: clear project visibility, autonomous execution, honest opinions
- **NEVER block main session** — spawn work and stay available
- **24/7 means 24/7** — dispatcher must NEVER stop overnight. "Late night" = don't alert Rob, NOT stop dispatching.
- **Be a COO** — prioritize and execute autonomously between conversations. Don't wait idle.

## NQ Execution Mode Architecture

### Mode names
- **FT-PL** = Forward Test — Paper on Live data (default ON)
- **BLE** = Broker Live Execution (default OFF)

### ⛔ BLE & PROP FIRM EVALS REQUIRE EXPLICIT ROB APPROVAL — NEVER ACTIVATE AUTONOMOUSLY

### NQ Live Strategy: GOD MODEL
- NOT individual strategies — those are components of a single unified God Model
- Do not reference individual strategy PFs when discussing live trading readiness

### Architecture (locked)
```
DATA:       NinjaTrader (Windows 192.168.68.88) → SMB /mnt/nt_bridge/bars.csv (ET timestamps)
            → nq-smb-watcher.service converts ET→UTC, appends to NQ_continuous_1min.csv
            → God Model inference on every bar (DRY_RUN=True)
EXECUTION:  (Future, Rob approves) Signal engine → TradersPost → Tradovate → Lucid prop accounts
```

### Services
- `nq-smb-watcher.service` — **ACTIVE LIVE FEED**
- `nq-dashboard.service` — Dashboard at port 8891
- `nq-tradovate-feed.service` — DISABLED (optional future upgrade)

### Data File
- `processed_data/NQ_continuous_1min.csv` — 403K+ rows, Jan 2025→present, all UTC
- Contracts roll quarterly — next roll NQM6 March 13 2026

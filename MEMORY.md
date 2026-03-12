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
- Ranking: `bt_pnl_pct` (compounded PnL %). Promotion: min 100 trades, PF≥1.35, MDD<50%, PnL>0. **FT demotion: PF<0.5 AND trades>500 only — never demote early, FT data is the goal.**
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

## Church Volunteer Coordinator (Mar 11 2026)

### What is it
Autonomous SMS system for Hastings Farms 2nd Ward Saturday church cleaning volunteers.
- **Repo:** https://github.com/robbyrobaz/church-volunteer-coordinator
- **Live:** https://church-volunteer-coordinator.vercel.app
- **Password:** `hastings2nd`

### Architecture
- **Textbelt** for SMS (switched from Twilio — no A2P registration needed)
- **Vercel** hosting with Upstash Redis for volunteer data
- **3 OpenClaw crons** (all Haiku, isolated sessions):
  - SMS Poll (every 2 min): zero tokens when idle, wakes AI only if unprocessed > 0
  - Daily Recruitment (10am): texts 2-3 people H→A order
  - Friday Reminder (Fri 10am): reminds Saturday volunteers

### Key decisions
- Contact order: H→A (reverse alpha, starting from H — Rob did Z→H manually)
- Sunday dates → always book nearest Saturday BEFORE (not after)
- **NO AI mention** — all SMS sign off as `-- Rob Hartwig` only
- **Household grouping:** singles contacted individually; couples/families with same `householdId` get texted together in one batch
- 30-day booking window only

### Spam prevention (after Mar 11 incident)
- Cache-busting headers on poll API (Vercel edge caching was causing stale reads)
- 5-minute per-phone duplicate protection
- Phone normalization: strip leading 1 (`14802323922` → `4802323922`)

### API quirks
- DELETE /api/signup to cancel (not PATCH)
- Outbound logging via POST /api/sms/outbound
- Poll returns `Cache-Control: no-store`

### Cron IDs
- SMS Poll: `12fd710c-e6ea-4ef0-970a-7bd0fd155ff2`
- Daily Recruitment: `46a5aa19-63c7-471d-bfe2-ed510eb409e2`
- Friday Reminder: `1debcdf0-b262-4113-8bd9-7b884900d879`

### Textbelt
- API key in TOOLS.md
- URL whitelist pending (can't send links until verified)
- ~$0.01/SMS

## NQ Dashboard Architecture (Mar 11 2026)

- **app_v3.py = THE ONLY NQ DASHBOARD = port 8895**
- `app.py` (port 8891) is LEGACY — do not use or modify
- Service: `nq-dashboard-v3.service`
- BT baseline comes from `strategies/orb/opus_review/` validated analysis (hardcoded)
- BLE Accumulated pulls from `live_trades` table

**Recovery lesson:** If dashboard seems missing, check `git reflog` — it shows detached HEAD commits. Never overwrite app_v3.py without checking reflog first.

## IBKR Historical Data (Mar 11 2026)

- **7 months of 1-min NQ data** (202,831 bars, Aug 2025 → Mar 2026)
- Script: `/home/rob/infrastructure/ibkr/scripts/download_nq_historical_1min.py`
- Output: `/home/rob/infrastructure/ibkr/data/NQ_ibkr_historical_1min.csv`
- **Workaround for error 10339:** Can't request continuous contract history — must stitch quarterly contracts (NQU5, NQZ5, NQH6)

### IBKR vs NinjaTrader Differences
- Avg OR HIGH diff: 8.07 pts
- Avg OR LOW diff: 11.00 pts
- Worst case: 193 pts
- **Conclusion:** NinjaTrader data is NOT reliable for validating IBKR strategies. Always use IBKR data for IBKR-targeted research.

## 15-min ORB Bug (Mar 11 2026)

**Bug:** Engine tracked OR window but state file showed null at entry time.

**Root cause:** `trade_date` was only set on position entry. During OR window it was `None`, so `new_day` check was always True. At entry start, `fresh_state()` wiped `or_high/or_low` before entry check ran.

**Fix:** Set `trade_date` when first capturing OR range, not just on position entry.

## Moonshot v2 Gate Changes (Mar 11 2026)

Per Rob's "FT is FREE" rule, promotion gates lowered:
- `MIN_BT_PF`: 2.0 → **1.0**
- `MIN_BT_PRECISION`: 0.40 → **0.20**
- File: `blofin-moonshot-v2/src/config.py`

## Lessons Learned

### ⛔ CRITICAL: Always READ the source first, never GUESS (Mar 12 2026)
**What happened:** Rob asked why the dispatcher wasn't dispatching cards. I guessed they were in Inbox without checking. Then read the file and saw they were already in Planned. Then got defensive instead of admitting the guess was wrong.

**The lesson:** 
1. **Always read the actual file/code/DB first** before making any claim about what's happening
2. **Never guess or assume** — check the reality
3. **When wrong, say it directly** — "I was wrong, I guessed without checking" — don't deflect or be evasive
4. The actual answer was correct: dispatcher ran at 12:13, cards were created after 12:13 by Auto Card Generator, next dispatch at ~12:43 would have picked them up. That's normal and working as designed.

**How to avoid:** Before answering "why didn't X happen," always:
- Read the relevant source code/instructions
- Check the actual state (curl APIs, logs, DB queries)
- Trace the timeline of events
- Only then answer

Don't make up explanations. It's annoying and wastes time.

- **Haiku WILL hallucinate** if not forced to call APIs explicitly. Must include step-by-step API call instructions with "WARNING: Do NOT make up data."
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

## BLE Execution Architecture — Prop Firm Constraints (weeks of research, Mar 2026)

### Tradovate prop firm accounts have NO API access
Platform-level restriction. No REST, no websocket, no fill data. This applies to Lucid Flex, FTMO, and all prop firm accounts at Tradovate. Not fixable, not configurable.

### TradersPost is the only path
Webhook middleware: our signal → TradersPost → Tradovate prop account. No other automated execution path exists for prop accounts. TradersPost has no pull API — webhook push only. We cannot retrieve trade history programmatically.

### BLE PnL is always estimated — never exact
Our engine detects trail stop hits from 1-min bar closes and fires a market exit. Actual Tradovate fill happens after bar close + webhook round-trip. On fast moves, fill can be 3-10pt worse than trail stop price. Real observed gap: 6.25pt ($500 on 4 contracts) on Mar 10 2026 trade ($1,360 estimated vs $860 actual).

Dashboard must always label BLE P&L as "~est." — never display it as ground truth.

## NQ Execution Mode Architecture

### Mode names
- **FT-PL** = Forward Test — Paper on Live data (default ON)
- **BLE** = Broker Live Execution (default OFF)

### ⛔ BLE & PROP FIRM EVALS REQUIRE EXPLICIT ROB APPROVAL — NEVER ACTIVATE AUTONOMOUSLY

### NQ Live Strategy: GOD MODEL
- NOT individual strategies — those are components of a single unified God Model
- God candidate gate: top 5 by FT PF, min 50 trades, min PF 1.35, recent 20-trade PF >= 1.0
- God cohesion bucket: 3-day joint forward test with strict consensus (min 2 agree, disagreements skip)
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

## NQ Data Source Hierarchy (Mar 11, 2026)

**CANONICAL SOURCE: IBKR**
- File: `/home/rob/infrastructure/ibkr/data/NQ_ibkr_1min.csv`
- Format: `YYYY-MM-DDTHH:MM:SSZ` (UTC)
- ORB engines read this FIRST

**FALLBACK ONLY: SMB/NinjaTrader**
- File: `processed_data/NQ_continuous_1min.csv`
- Only for historical backtest or if IBKR unavailable
- **Values differ from IBKR — never compare them directly**

**Lesson:** The engine uses IBKR. Don't debug by comparing to SMB data.

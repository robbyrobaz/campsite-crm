# PROJECTS.md — Active Project Board

> **Strategic project overview.** Kanban board (:8787) is the live work queue.
> This file is the high-level view — project status, architecture, what matters.
> Last updated: 2026-02-26

---

## 🟢 ACTIVE (Primary Focus)

### 0. IBKR Options Pipeline ⭐ NEW
**Repo:** `robbyrobaz/ibkr-pipeline` (private) | **Path:** `~/infrastructure/ibkr/`
**Status:** Infrastructure DONE. Waiting on OPRA subscription (~Thursday Mar 5 when $500 clears).
**PRD:** `brain/PRD_OPTIONS_PIPELINE.md` — APPROVED, ready to build

**Infrastructure (all live):**
- IB Gateway Docker running, port 4002, paper account DUH860616
- Redis port 6379 ✅ | DuckDB `data/options.duckdb` ✅
- ib_async venv installed, all pipeline modules clean
- Historical data confirmed: SPX chain, NQ futures, option bars all working
- No 2FA on paper — auto-reconnects nightly at 11:59 PM

**Build sequence (post-OPRA Thursday):**
1. Card 1: Live skew monitor — stream ATM±3% SPX strikes, compute z-score signals
2. Card 2: Paper trade executor — credit spreads, TP/SL/time stops, PDT guard
3. Card 3: NQ signal bridge — God Model → QQQ options

---

### 1. NQ Futures Trading Pipeline
**Repo:** `NQ-Trading-PIPELINE/` | **Path:** `/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE/`
**Dashboard:** http://127.0.0.1:8891 (also :8891 on LAN)
**GitHub:** https://github.com/robbyrobaz/NQ-Trading-PIPELINE (private, main branch)
**Status:** Forward Test (FT-PL) running on live data. BLE off (`DRY_RUN`). 8 models active.

### ⭐ 1a. NQ ORB Engine — LIVE EXECUTION (separate from God Model FT)
**Engine:** `NQ-Trading-PIPELINE/pipeline/orb_signal_engine.py`
**Service:** `nq-orb-signal.service` (active, DRY_RUN=False)
**Route:** IBKR L2 feed → ORB engine → TradersPost → Tradovate → Lucid Flex 50K LFE0506429036012
**Status:** LIVE — tested Mar 6 (SHORT +$43) and Mar 9 (LONG +$27). Both clean. ✅
**Backtest:** 14 months, PF 6.4, WR 86.3%, $4,772/mo EV at 4 MNQ (Lucid Flex 50K)

**Production config:** TEST_MODE=False, OR_OFFSET=30, QUANTITY=1, **UTC hour=13** (DST-corrected Mar 9)
**NY open post-DST:** 9:30 AM EDT = 13:30 UTC = 6:30 AM MST. Engine fires at 13:30 UTC. ✅
**DST fix committed:** `fec3864` — was hardcoded hour=14 (EST), corrected to hour=13 (EDT)
**Next:** Scale to QUANTITY=4 after first clean live Monday run (today's 6:30 AM). Add 15-min ORB layer.

**Live data feed:** NinjaTrader (Windows 192.168.68.88) → SMB `/mnt/nt_bridge/bars.csv` → `nq-smb-watcher.service` → `NQ_continuous_1min.csv`
**Forward test run_id:** `smb_live_forward_test` (only valid run — 129 trades Feb 23-26)
**Alert topic:** ntfy.sh/nq-pipeline

**Forward Test Results (Feb 23-26):**
- momentum: 99 trades, 62% WR, +$5,900 ✅
- vol_contraction: 13 trades, 62% WR, +$160 ✅
- gapfill: 7 trades, 14% WR, -$2,565 ❌ (investigate)
- vwapfade: 9 trades, 11% WR, -$2,750 ❌ (investigate)
- Feb 26 had 100 trades in one day — possible overtrading during volatile session

**Strategy Registry (all tier=1, gate_status=pass):**
- equal_tops_bottoms: PF 3.02, Sharpe 7.97 (NOT YET in live inference — add to God Model)
- orb: PF 2.92, Sharpe 7.59
- momentum: PF 2.82, Sharpe 7.38 (carrying live forward test)
- vwap_fade: PF 2.17, psych_levels: PF 1.92, gap_fill: PF 2.07, vol_contraction: PF 1.96

**God Model:** Ensemble dispatcher — runs all experts per bar, dispatches highest-confidence signal. Tournament table tracks challenger vs champion.

**Next actions:**
- [ ] Register equal_tops_bottoms in live God Model inference (high priority — best PF, not generating signals)
- [ ] Investigate gapfill and vwapfade live signal quality (14% WR is broken)
- [ ] Investigate Feb 26 trade flood (100 trades in one day — momentum firing too aggressively?)
- [ ] Run God Model tournament update to include ETB as challenger
- [ ] Verify psych_levels is generating live signals

**Constraints:**
- ⛔ FT-PL only by default (live data + paper trades). BLE remains OFF (`DRY_RUN`) — no TradersPost webhooks/live orders/prop eval activation without Rob's explicit approval.
- ⛔ God Model = single unified ensemble, NOT individual strategies
- SMB mount is read-only — never write to `/mnt/nt_bridge/`

---

### 1b. Moonshot v2 ⭐ NEW (2026-03-02)
**Repo:** https://github.com/robbyrobaz/blofin-moonshot-v2 | **Path:** `/home/rob/.openclaw/workspace/blofin-moonshot-v2/`
**Dashboard:** http://127.0.0.1:8893
**Status:** LIVE — first cycle complete, data accumulating, tournament not yet active (needs labels + first challengers)

**Architecture (clean rewrite from scratch):**
- 343 USDT pairs, dynamic discovery every 4h
- Tournament ML: challengers → backtest gate (PF≥2.0, prec≥40%, 50+ trades) → forward test → champion by FT PnL
- 50 features: price/volume/volatility/structure + funding rate + OI + mark price + tickers + social signals
- Social (Tier 1 free): Fear & Greed, CoinGecko trending, RSS feeds, Reddit, GitHub
- Path-dependent labels (hit +30% BEFORE -10%), PnL-weighted training, bootstrap CI on PF
- Per-model entry/invalidation thresholds (never fixed global values)
- Separate long + short champions

**Services:** moonshot-v2.timer (4h), moonshot-v2-social.timer (1h), moonshot-v2-dashboard.service
**Old moonshot:** fully shut down (service, timer, dashboard, 2 crons — all disabled)

**Next actions:**
- [ ] Trigger cycle now with 14-month candle history imported from v1 (865K rows)
- [ ] Regenerate labels with full history, then run tournament
- [ ] Add missing PRD features: backfill.py, extended data, social improvements
- [ ] Confirm no service confusion — all services now named moonshot-v2-*

---

### 2. Blofin Trading Pipeline
**Repo:** `blofin-stack/` | **Path:** `/home/rob/.openclaw/workspace/blofin-stack/`
**Dashboard:** http://127.0.0.1:8892
**Status:** Paper trading active (86K+ trades). Post-bug-fix rebuild phase.

**Current Tier State:**
- T2 (live-eligible): 12 strategies
- T1 (promoted, monitoring): 9 strategies
- T0 (backtesting): 7 strategies
- T-1 (demoted/failing): 3 strategies

**Top performers by FT PF (min 20 FT trades):**
- vwap_volatility_rebound: FT PF 2.21, T2
- volume_volatility_mean_reversion: FT PF 1.51, T2
- cross_asset_correlation: FT PF 1.40, T2

**Pipeline runs every 4h** via cron (Haiku): `orchestration/run_pipeline.py`

**Next actions:**
- [ ] Diagnose T1/T2 strategies with gate_status=fail (momentum T2, volatility_regime_switch T2, atr_contraction_breakout T2 — all fail with no FT data)
- [ ] Investigate strategies with large BT/FT PF divergence (overfitting or regime change?)
- [ ] Phase 2 ML retrain scheduled ~March 1 — verify gate conditions
- [ ] Fix 3 breakout strategies with syntax error (line 41)
- [ ] Analyze paper trading slippage patterns

---

## 🟡 SECONDARY (active but not primary focus)

### 3. Church Volunteer Coordinator ⭐ NEW
**Repo:** `church-volunteer-coordinator/` | **Path:** `/home/rob/.openclaw/workspace/church-volunteer-coordinator/`
**Live:** https://church-volunteer-coordinator.vercel.app | **Password:** `hastings2nd`
**Status:** LIVE — 3 crons running, fully automated

Autonomous SMS system for Hastings Farms 2nd Ward Saturday church cleaning.
- **SMS Provider:** Textbelt (switched from Twilio — simpler, no A2P registration)
- **Crons:** SMS Poll (2min), Daily Recruitment (10am), Friday Reminder (Fri 10am)
- **Volunteers:** 175 total, 106 contacted (Z→H by Rob), 67 remaining for automation (H→A)

**Current Calendar:**
- Mar 14: Rob Hartwig
- Mar 21: Adam Little
- Mar 28: Rob Hartwig

**Pending:** Textbelt URL whitelist approval (links blocked until verified)

---

### 4. Jarvis Home Energy Dashboard
**Repo:** `jarvis-home-energy/` | **Port:** 8793
**Status:** Live. Nest/SPAN/Tesla/Wyze/GE appliances integrated.
**Known issue:** Washer showing "disconnected" despite GE API showing ONLINE — investigation mid-stream (GE services all stale: lastSyncTime 17 days old)
**Blocked:** Ring integration (2FA lockout — complete interactively when lockout clears)

### 5. Numerai Tournament
**Models:** robbyrobml, robbyrob2, robbyrob3 (submitting daily)
**Status:** Stable. Era-boosting promising but full retrain pending.
**Not a primary focus right now.**

---

## 🔴 PAUSED / BACKLOG

- HedgeEngine / Sports Betting Arb Scanner — deployed, waiting on Rob for next features
- Gilbert PD Radio Trainer — scaffolded, parked
- Campsite CRM — not started

---

## ⚙️ AUTONOMOUS OPERATIONS

### Cron Schedule
| Cron | Schedule | Model | Purpose |
|------|----------|-------|---------|
| Auto Card Generator | Every hour :00 | Sonnet | Reads NQ + Blofin state, creates 2 NQ + 1 Blofin cards and **launches immediately** (gates if In Progress ≥ 6) |
| Blofin Strategy Pipeline | Every 4h :15 | Haiku | Runs `run_pipeline.py` — backtests, promotes/demotes strategies |
| Jarvis Pulse (Dispatch) | Every 30min | Sonnet | Health checks, dispatches any lingering Planned cards, recovers stale In Progress |
| Hourly Oversight | Every 2h :30 | Haiku | HEARTBEAT.md — server health, services, git hygiene |
| AI Token Usage Audit | Weekly Sun 8am | Haiku | Token efficiency report |

### Kanban Workflow
- **Inbox = ONLY for real-money decisions (BLE, live trading). Dispatcher ignores)
- **Planned** = should be near-zero. Auto-generator launches cards immediately. If cards are stuck here, dispatcher picks them up within 30min.
- **In Progress** = builder working
- **Done** = complete (skip Review/Test entirely)

### Auto-generation logic
- Instructions: `brain/AUTO_CARD_GENERATOR.md`
- Gate: if In Progress >= 6, skip cycle
- Creates and **launches** work immediately based on live pipeline data — no sitting in Planned

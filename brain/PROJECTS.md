# PROJECTS.md — Active Project Board

> **Strategic project overview.** Kanban board (:8787) is the live work queue.
> This file is the high-level view — project status, architecture, what matters.
> Last updated: 2026-02-26

---

## 🟢 ACTIVE (Primary Focus)

### 1. NQ Futures Trading Pipeline
**Repo:** `NQ-Trading-PIPELINE/` | **Path:** `/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE/`
**Dashboard:** http://127.0.0.1:8891 (also :8891 on LAN)
**GitHub:** https://github.com/robbyrobaz/NQ-Trading-PIPELINE (private, main branch)
**Status:** Live forward test running. DRY_RUN mode. 8 models active.

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
- ⛔ DRY_RUN only — NO live orders, NO TradersPost webhooks, NO prop firm eval activation ever without Rob's explicit approval
- ⛔ God Model = single unified ensemble, NOT individual strategies
- SMB mount is read-only — never write to `/mnt/nt_bridge/`

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

### 3. Jarvis Home Energy Dashboard
**Repo:** `jarvis-home-energy/` | **Port:** 8793
**Status:** Live. Nest/SPAN/Tesla/Wyze/GE appliances integrated.
**Known issue:** Washer showing "disconnected" despite GE API showing ONLINE — investigation mid-stream (GE services all stale: lastSyncTime 17 days old)
**Blocked:** Ring integration (2FA lockout — complete interactively when lockout clears)

### 4. Numerai Tournament
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
- **Inbox** = idea bucket (dispatcher ignores — Rob's scratchpad)
- **Planned** = should be near-zero. Auto-generator launches cards immediately. If cards are stuck here, dispatcher picks them up within 30min.
- **In Progress** = builder working
- **Done** = complete (skip Review/Test entirely)

### Auto-generation logic
- Instructions: `brain/AUTO_CARD_GENERATOR.md`
- Gate: if In Progress >= 6, skip cycle
- Creates and **launches** work immediately based on live pipeline data — no sitting in Planned

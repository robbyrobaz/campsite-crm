# PROJECTS.md — Active Project Board

> **Strategic project overview.** Kanban board (:8787) is the live work queue.
> This file is the high-level view — project status, architecture, what matters.
> Last updated: 2026-04-04

---

## 🟢 ACTIVE (Primary Focus)

### NSF SBIR Phase I — OPEN NOW ⭐ NEW (Apr 4 2026)
**Program:** NSF 24-579 | **Phase I Award:** $275K | **Duration:** 6-12 months
**Status:** Rolling Project Pitch submissions → quarterly full proposal deadlines
**Apply:** https://seedfund.nsf.gov/apply/project-pitch/

**Why This Fits OpenClaw:**
- Broad tech mandate: AI, robotics, advanced manufacturing all eligible
- Non-dilutive funding, no equity taken
- Requires R&D intensity (multi-agent coordination, safety boundaries, autonomous decision-making)
- Strong commercial potential (software testing, cybersecurity ops, DevOps automation)

**Next Actions:**
- [ ] Draft 2-page Project Pitch (decide angle: QA automation vs cybersec vs DevOps)
- [ ] Submit pitch to NSF seedfund portal
- [ ] Monitor DoD SBIR 25.4 reauthorization (imminent — awaiting presidential signature)

**Estimated Timeline:** Pitch submission → invite decision ~4 weeks → full proposal at next quarterly deadline

---



### 0. Hyperliquid S&P 500 Pipeline ⭐ NEW (Mar 20 2026)
**Repo:** `hyperliquid-sp500-pipeline/` | **Path:** `/home/rob/.openclaw/workspace/hyperliquid-sp500-pipeline/`
**Dashboard:** http://127.0.0.1:8897 | **Services:** `sp500-ingestor.service`, `sp500-dashboard.service`
**GitHub:** https://github.com/robbyrobaz/hyperliquid-sp500-pipeline (private)
**Status:** Data pipeline LIVE. SPY backfill running. Paper trading ready once backfill completes.

**Contract:** `xyz:SP500` on Trade[XYZ] perp dex (Hyperliquid L1 blockchain)
- 50x max leverage, isolated margin, USDC settled, 24/7 trading
- Officially licensed by S&P Dow Jones Indices (launched Mar 18 2026)
- Oracle: institutional S&P DJI data feed

**Architecture:**
- WebSocket ingestor → DuckDB (1-min candles)
- 10 strategies ported from NQ pipeline (ORB variants, momentum, power hour, FVG, london killzone)
- Backtester + paper engine + executor stub
- Historical data: IBKR SPY × 10 as proxy (365 days backfilling)

**API Key Detail:** All requests need `"dex":"xyz"` parameter for Trade[XYZ] assets

**Next actions:**
- [ ] Complete SPY 1-year backfill via IBKR (~1 hour)
- [ ] Run backtests on all 10 strategies
- [ ] Start paper trading
- [ ] Configure CyberGhost VPN (UK dedicated IP) for live trading
- [ ] ⛔ Live trading requires Rob's explicit approval + VPN active

---

### 1. IBKR Options Pipeline ⭐ NEW
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
**Dashboard:** http://127.0.0.1:8895 (v3, also :8895 on LAN) | **Service:** `nq-dashboard-v3.service`
**GitHub:** https://github.com/robbyrobaz/NQ-Trading-PIPELINE (private, main branch)
**Status:** 23 strategies in FT. 2 live BLE engines paying out. All-time BLE: 7 trades, $5,118, 86% WR.

### ⭐ 1a. NQ ORB Engine — LIVE BLE EXECUTION
**Live BLE strategies (2):**
| Strategy | Engine | Service | DRY_RUN |
|----------|--------|---------|---------|
| `orb` | `pipeline/orb_signal_engine.py` | `nq-orb-signal.service` | False (LIVE) |
| `orb_15min` | `pipeline/orb_15min_signal_engine.py` | `nq-orb15-signal.service` | False (LIVE) |

**Route:** IBKR data → engine → TradersPost → Tradovate → Lucid Flex 50K (LFE0506429036015)
**All-time BLE PnL:** 7 trades, $5,118, 86% WR, PF 24.3 (as of Mar 13 2026)
**BT Baseline:** 14mo backtest, PF 6.4, WR 86.3%

### Dashboard Strategy Library — Display Rules (Mar 13 2026)
The Strategy Library is a **combined FT competition board** — all strategies that may eventually promote to BLE.

**Status badge logic:**
- `BLE` (green) = live with real broker NOW. Only `orb` + `orb_15min`.
- `FT` (green) = paper trading on live IBKR data. Competing for BLE promotion.
- `OFF` (grey) = disabled (`live_enabled=0`). Not trading.
- `BLKD` (dark) = blacklisted (circuit broken).

**Type badge logic (shown after status):**
- `RULE` (amber) = rule-based strategy (deterministic, no ML model)
- `ML` (blue) = machine learning strategy (trained model + confidence score)

**Architecture rule:** FT and BLE are NOT separate tracks. Any strategy can be promoted to BLE by Rob after proving itself in FT. The BLE badge in the library shows which are live today.

**Top section (ORB Live Engines) is entirely BLE** — "BLE Today", "BLE Accumulated", "Drift (BLE vs BT)" all correct there. That section ≠ Strategy Library.

### Current 23-Strategy Registry (Mar 13 2026)
**BLE Live:** `orb` (ML), `orb_15min` (RULE)
**FT Rule-based (6):** orb_rth (PF 99), orb_multi_5min (PF 5.76), orb_multi_15min (PF 5.34), orb_retest_15min (PF 2.61), orb_retest_5min (PF 1.52)
**FT ML (13):** london_killzone (PF 3.62), momentum (PF 3.04), power_hour (PF 3.02), fair_value_gap (PF 3.02), equal_tops_bottoms (PF 3.01), measured_move, initial_balance_ext, ema_pullback, vol_contraction, liquidity_sweep, vwap_fade, prev_day, gap_fill
**OFF (4):** equal_tops_bottoms, overnight_range_breakout, psych_levels, opening_drive

**Known pending issues:**
- [ ] `ft_trades` column in strategy_registry shows 0 — paper_trades → registry sync not wired in nq_watcher.py
- [ ] `prev_day` expert showing PDH=19040 (2025 levels) — feature builder date grouping bug

**Live data feed:** IBKR → `NQ_ibkr_1min.csv` → `nq-data-sync.service` → `NQ_ibkr_ft.csv`
BLE engines read IBKR original directly. Dashboard + on-demand backtests read the synced copy. Zero contention.

**Next BLE promotion candidates (by BT PF, need FT validation):**
1. orb_rth (PF 99, rule-based — needs FT data)
2. orb_multi_5min (PF 5.76) / orb_multi_15min (PF 5.34)
3. orb_retest_15min (PF 2.61) — strongest retest candidate

**Constraints:**
- ⛔ Only Rob can promote a strategy to BLE. Never change `ORB_ENGINES` or flip `DRY_RUN=False` without explicit approval.
- ⛔ Never modify the two live BLE engine services without explicit approval.
- ⛔ God Model = single unified ensemble, NOT individual strategies

---

### 1b. Moonshot v2 ⭐ REDESIGNED (2026-03-16)
**Repo:** https://github.com/robbyrobaz/blofin-moonshot-v2 | **Path:** `/home/rob/.openclaw/workspace/blofin-moonshot-v2/`
**Dashboard:** http://127.0.0.1:8893
**Status:** LIVE — Dual-track system deployed (rule-based entry + ML tournament)

**Architecture — DUAL-TRACK SYSTEM:**

**Track 1: Rule-Based Entry (NEW — PRIMARY)**
- **Auto-enter ALL coins ≤7 days old** (ML can't predict bar 0-10 spikes)
- Position: 2% per coin, 2x leverage
- Exit: Trailing stop (activate +15%, trail 10% back), hard stop -5%
- Horizon: 42 bars (7 days)
- **Validation:** 60% WR, avg PnL +26.1%, **PF 7.53** on 5 spike coins
- **Why it works:** 76% of 30%+ moves happen in first 7 days before ML has data

**Track 2: ML Tournament (coins 30+ days old)**
- 343 USDT pairs, dynamic discovery every 4h
- Tournament ML: challengers → backtest gate → forward test → champion by FT PnL
- 50 features: price/volume/volatility + funding/OI + social signals
- Path-dependent labels (hit +30% BEFORE -5%), PnL-weighted training
- Separate long + short champions

**Services:** moonshot-v2.timer (4h), moonshot-v2-social.timer (1h), moonshot-v2-dashboard.service

**Key files:**
- `src/execution/new_listing_entry.py` — rule-based logic
- `brain/MOONSHOT_V2_REDESIGN.md` — full proposal + risk assessment
- `brain/SPIKE_RESEARCH_SUMMARY.md` — research findings + deployment guide
- `config.py` — NEW_LISTING_ENABLED=True

**Next actions:**
- [ ] Monitor first 3-5 new coin entries (watch for edge validation)
- [ ] After 20+ trades: verify PF >1.5 sustained
- [ ] Dashboard: add "New Listing Tracker" section

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
- Apr 11: Rob Hartwig

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

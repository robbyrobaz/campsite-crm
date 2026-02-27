# MEMORY.md — Learnings & Reference

> Project status lives in `brain/PROJECTS.md`. This file is for lessons learned, preferences, and reference info only.

## Architecture Reference

### Blofin Stack — Per-Coin Strategy (Key Design Decision, Feb 25 2026)
**Do NOT build per-coin ML models.** Global models (entry_classifier, direction_predictor, etc.) stay trained on all coins — that's correct.

**The right approach:** Use FT performance data to find which coin+strategy pairs respond well to the global model. Enable only those pairs. Already built:
- `strategy_coin_performance` — 32 coins × 26 strategies, BT + FT metrics per pair
- `strategy_coin_eligibility` — 1,112 rows, live per-coin performance with blacklist
- Pipeline fix (Feb 25 2026): ensures good per-coin BT results flow through to FT promotion

**The loop:** Global model → per-coin FT data shows which coins respond → eligibility enables/disables pairs → only winning coin+strategy combos trade.

**Dashboard rule (Feb 25 2026):** NEVER show aggregate/system-wide PF, WR, or PnL on any dashboard. It lumps winners with losers and is meaningless. Always show **Top 10 pairs by FT profit factor** (min 20 FT trades). The system-wide numbers look terrible because they include hundreds of bad pairs — the signal is in the top performers only.

### Blofin Stack
- Feature library: 95+ technical indicators
- Backtester: 7-day historical replay, multi-timeframe
- ML pipeline: 5 models (direction, risk, price, momentum, volatility)
- Ranking: strategies ranked by `bt_pnl_pct` (compounded PnL %). Promotion gates: min 100 trades, PF≥1.35, MDD<50%, PnL>0. FT demotion: PF<1.1 or MDD>50% after 20 FT trades.
- Paper trading reality gap: slippage 0.052%/side (2.6x worse than assumed), fill rate 67%, stops too tight (47% hit then reversed)

### Numerai
- 3 models: robbyrobml, robbyrob2, robbyrob3
- API keys in `.env` in numerai-tournament/
- Era-boosting: 300 trees × 4 rounds, fixed tree count (no early stopping on boost rounds)
- Baselines: robbyrobml val_corr=0.02916 Sharpe=1.40

### Model Strategy
- Subscription: Claude Max 5x ($100/mo flat). Resets every 5 hours.
- Model routing: Sonnet for all reasoning/code/main session. Haiku for cron jobs, health checks, lightweight tasks. Opus is banned.

## Lessons Learned

- **Subagents die on heavy data tasks.** Multi-GB parquet loads → run in main session, not builders.
- **Builders die silently.** Always check sessions_list after spawn. 3 Numerai builders died with 0 messages (Feb 19).
- **Monitoring crons for completed tasks = noise.** Only monitor active spawns. Check status.json for completed work.
- **Claude rate limits are per-minute** (1000 RPM), not per billing window.
- **Volume column in Blofin ticks is tick count, not real volume.** All volume-spike thresholds need ≤0.8 multiplier to bypass.
- **Smoke test uses 5K ticks (~10 candles)** — too few for strategies needing 25+ candle warmup.
- **Agent Teams need interactive mode** — no `-p` flag. Must accept permissions prompt (option 2).
- **Git LFS rejects >2GB objects** — exclude large data files from backup sweeps.
- **Numerai full dataset OOMs with 740 features on 32GB RAM.** Use v2_equivalent (304 features). OOM also kills OTHER processes (gateway died as collateral).
- **pandas dropna() breaks index alignment with numpy.** Always `reset_index(drop=True)` after dropna before passing to model.predict().

## Rob's Preferences
- Concise updates, not walls of text
- Tell him what you did, not what you're about to do
- Lead with bad news
- Hates: babysitting AI, temp files in repos, being asked questions he already answered
- Wants: clear project visibility, autonomous execution, honest opinions
- **NEVER block main session** — spawn work and stay available. Rob got angry when I was unavailable 5 min (Feb 19)
- **24/7 means 24/7** — The dispatcher must NEVER stop working overnight. "Late night" only means don't alert Rob, NOT stop dispatching. Lost 8 hours of productivity overnight Feb 19-20 because of a "quiet mode" that nobody asked for.
- **Rate limit strategy:** 5h window is the real constraint (caused the crash). 7-day has never actually throttled us even at 92%. Only go to "super light mode" (Haiku/Mini only) if 7-day hits 99%. Token tracker now pulls real utilization % from Anthropic OAuth API.
- **Opus is BANNED (Feb 25, 2026):** Discovered main session was silently running Opus the whole time despite notes saying Sonnet. Gateway config `openclaw.json` `.agents.defaults.model.primary` must be `anthropic/claude-sonnet-4-6`. Fallback is Haiku only. Opus removed from routing entirely. Rob was very angry about this — never let Opus back in.
- **Use the kanban board** — don't discount visual tools. Markdown files are not enough for project tracking.
- **Be a COO** — prioritize and execute autonomously between conversations. Don't wait idle.

## Infrastructure Reference
- **Claw-Kanban:** port 8787, systemd `claw-kanban.service`, SQLite DB at `kanban-dashboard/kanban.sqlite`
- **Kanban status semantics:** Inbox=idea bucket (dispatcher ignores), Planned=do it now (dispatcher picks up within 30min), In Progress=running, Review/Test=SKIP (go straight to Done), Done=complete
- **Auto Card Generator:** Hourly cron (Sonnet), creates 2 NQ + 1 Blofin cards in Planned. Gates if Planned+InProgress≥2. Instructions: `brain/AUTO_CARD_GENERATOR.md`
- **Dispatcher (Jarvis Pulse):** Every 30min, **Sonnet** (upgraded from Haiku Feb 26 — dispatching requires reasoning). Full 8-phase protocol: `brain/DISPATCHER.md`. Max 3 concurrent In Progress (raised from 1, Feb 26).
- **NQ Research Scientist cron:** REMOVED Feb 26 2026 — was pointing to wrong dir, timing out. Replaced by Auto Card Generator.
- **Agent files:** `.claude/agents/` — ml-engineer, dashboard-builder, devops-engineer, qa-sentinel, crypto-researcher
- **Numerai "medium" feature set = 740 features** (misleading). v2_equivalent = 304. Full dataset OOMs with 740 on 32GB RAM.

## Session Context Gap Fix (Feb 26 2026)
**Root cause of Rob repeating himself every day:** New sessions weren't reading `memory/YYYY-MM-DD.md`. An entire session's work (cron overhaul, doc audit, Blofin gate corrections, new brain files) was invisible to the next session. Fixed by:
1. AGENTS.md startup sequence now explicitly requires reading daily memory (NON-OPTIONAL note added)
2. BOOTSTRAP.md updated with NON-OPTIONAL callout for daily memory + all critical facts from Feb 26 session
3. This MEMORY.md entry distilling the Feb 26 changes

**Feb 26 2026 session summary (critical changes):**
- EEP scoring: DEAD. Blofin ranks by `bt_pnl_pct`. Gates: min 100 trades, PF≥1.35, MDD<50%, PnL>0. Demotion after 20 FT trades if PF<1.1 or MDD>50%. Early crash-stop: PF<0.5 with ≥5 FT trades.
- Jarvis Pulse upgraded to Sonnet (dispatching requires reasoning, Haiku was making bad card choices)
- NQ Research Scientist cron removed (broken path, replaced by Auto Card Generator)
- blofin README, HEARTBEAT.md, AGENTS.md, PROJECTS.md all audited: Opus removed, port 8888→8892, IBKR retired, EEP references purged
- `brain/AUTO_CARD_GENERATOR.md` and `brain/DISPATCHER.md` created — full pipeline context for cron agents

## OpenClaw Ops Memory (Feb 21, 2026)

- Canonical OpenClaw install is user-global only: `/home/rob/.npm-global/lib/node_modules/openclaw` (`2026.2.19-2`).
- Removed stale ghost install `/usr/lib/node_modules/openclaw` (`2026.2.9`), which had created duplicate binaries.
- After ghost cleanup, gateway service failed because systemd unit still pointed at `/usr/lib/node_modules/openclaw/dist/index.js`.
- Fixed by reinstalling service with force so `ExecStart` points to `/home/rob/.npm-global/lib/node_modules/openclaw/dist/index.js`.
- Cron model cleanup: replaced disallowed `model=sonnet` overrides with `model=openai-codex/gpt-5.3-codex` in `~/.openclaw/cron/jobs.json`.
- Default model strategy: primary is `openai-codex/gpt-5.3-codex`, with stronger-first fallbacks.
- Freeze symptom after ~15h uptime: gateway appeared alive but bot responsiveness degraded.
- Working recovery sequence:
- `systemctl --user restart openclaw-gateway.service openclaw-browser.service`
- `openclaw health`
- `openclaw cron run 36f47279-520f-4ce7-8f9c-a7c44be0771a --expect-final --timeout 180000`
- Post-fix validation: Jarvis cron resumed with `status=ok` and model `gpt-5.3-codex`.

## NQ Pipeline Reference (Updated Feb 24, 2026)

### equal_tops_bottoms — REHABILITATED (Feb 26 2026)
Was wrongly blacklisted with "PF 0.68 no edge" — that eval was broken. Actual WF data:
10/10 folds pass prop sim, PF 2.78–3.27, Sharpe 7.34–8.62, ~2000+ OOS trades/fold. Unblacklisted.
Pattern: tweezer tops/bottoms (ICT equal highs/lows) on 5-min NQ. Rob sees this in live trading.
ML feature research card dispatched to find best entry conditions + add as God Model expert #7.

### Definitive Phase 2 Leaderboard (All Filters Corrected)
1. momentum: PF 2.91, Sharpe 7.68, Calmar 808, ~9 trades/day
1. orb: PF 2.92, Sharpe 7.59, ~3 trades/day  ← TIED #1 (target_horizon=10, confirmed Feb 25)
3. gap_fill: PF 2.10, Sharpe 5.56, ~5.6 trades/day
4. vwap_fade: PF 2.08, Sharpe 5.56, ~8.6 trades/day
5. prev_day: PF 2.03, Sharpe 5.33, ~0.84 trades/day
6. vol_contraction: PF 1.86, Sharpe 4.70, ~4.1 trades/day
All 6 pass Lucid gates. Phase 3 Tier 1: momentum + orb.
ORB improvement: target_horizon 5→10 bars = +14.6% PF, +14.6% Sharpe, +2.9pp WR. 10/10 folds pass Lucid sim.

### NQ Filter Inflation Bug (Fixed)
- `_CANDIDATE_CFG` in `run_phase2.py` was overriding `max_trades_per_session=100` for all strategies
- gap_fill: 49K → 6.9K signals after fix (+25% PF)
- momentum: 18K → 7.5K signals (+2.4% PF)
- Any new strategy must have correct session cap in `_CANDIDATE_CFG`, not 100

### ML Exit God-Model — Key Findings
- Dominant feature: `pnl_drawdown_from_peak` at 73% — model IS a trailing stop
- Failed to improve PF on test period (losing regime for all strategies)
- Better alternative: ATR trailing stop (simpler, same behavior)
- Code is in `pipeline/exit_ml_engine.py` + `strategies/exit_ml_strategy.py` for future reference

### Home Energy Dashboard Credentials (jarvis-home-energy/config.py)
- Wyze: KEY_ID=ec0dd323-1db4-4e81-8cd4-a4feab256bae, API_KEY=Fn1phBRix8ifLx0t5f3ktIyVfz2uRBSWdipswwjAiEJ0Z8SIAmVnaCNZLoOL
- Nest SDM project_id=edc12ede-0076-42d4-86d8-c87f49aec4b4, refresh_token saved in config.py
- 3 Wyze cameras: Front Side (D03F275A9799), Upstairs (2CAA8E813AE9), Downstairs (2CAA8E813B36)
- 2 Nest thermostats: Downstairs + Loft upstairs (both COOLING)
- wyze-sdk 2.2.0 has NO snapshot method — cameras show status only, no live feed
- Ring invite: jarvis.is.my.coo@gmail.com — 14-day window (received Feb 23 9:50 PM)

## Camera Setup (Feb 25, 2026)

### Jarvis Home Energy — Cameras Page
- **Upstairs Cam** (2CAA8E813AE9, 192.168.68.51): direct RTSP `rtsp://Camera:Feed@192.168.68.51/live`
- **Downstairs Cam** (2CAA8E813B36, 192.168.68.82): direct RTSP `rtsp://Camera:Feed@192.168.68.82/live`
- **Front Side Cam** (D03F275A9799, 192.168.68.76): newer firmware blocks RTSP → uses **docker-wyze-bridge**
  - wyze-bridge RTSP: `rtsp://127.0.0.1:8554/front-side-cam`
  - docker-wyze-bridge v2.10.3, host network mode, compose at `workspace/wyze-bridge/docker-compose.yml`
  - Creds in `wyze-bridge/.env` (single-quoted password for $ and # chars)
- **Frame serving**: background ffmpeg threads per camera → cache latest JPEG → `/api/camera/<id>/frame` responds in ~11ms
- **JS polling**: 500ms refresh per camera via `_camRefreshTimers`; `_getRtspId()` maps cam name → stream id
- **Blofin dashboard moved** to port 8892 (was 8888) to free port 8888 for wyze-bridge mediamtx

### Tesla Fleet API Token Refresh (Feb 25, 2026)
- Cache file: `jarvis-home-energy/tesla_cache.json` — tokens under `["rob.hartwig@gmail.com"]["sso"]`
- teslapy's own `.refresh_token()` returns 404 — do NOT use it
- **Working refresh**: `POST https://auth.tesla.com/oauth2/v3/token` with `{grant_type, client_id:"ownerapi", refresh_token, scope}`
- Token expires every 8 hours — `_get_tesla_fleet_token()` in app.py auto-refreshes 5 min before expiry
- Fleet API base: `https://owner-api.teslamotors.com/api/1/energy_sites/2252397277512276/`
- Key endpoint: `/live_status` → solar_power, battery_power, grid_power, load_power, grid_status
- **Status as of Feb 25 night**: grid=7065W (house load), solar=0W (dark), soe=0% (Gateway 3, no Powerwall)

## Feb 26-27 Session — Critical Changes (Permanent Reference)

### Cron System Overhaul
- **Removed:** NQ Research Scientist (broken — wrong path, timeouts)
- **Added:** Auto Card Generator (hourly :00, Sonnet) — reads live NQ+Blofin state, creates 2 NQ + 1 Blofin Planned cards. Gates if Planned+InProgress ≥ 2
- **Upgraded:** Jarvis Pulse dispatcher Haiku → Sonnet (dispatch logic too important for Haiku)
- **Max concurrent In Progress:** 3 (was 1)
- Dispatcher reads `brain/DISPATCHER.md` — enriches vague cards, verifies deploy after builder done

### Blofin Promotion Gates (EEP IS DEAD — use these)
- Ranking field: `bt_pnl_pct` (compounded PnL%), NOT EEP score
- Promotion: min 100 BT trades, PF≥1.35, MDD<50%, PnL>0
- FT demotion: PF<1.1 or MDD>50% after 20 FT trades
- Early crash-stop: PF<0.5 with ≥5 FT trades
- Per-coin ML models are banned — global models only, per-coin eligibility table handles coin selection

### NQ Forward Test State (Feb 26)
- run_id=`smb_live_forward_test`, 129 trades
- momentum: +$5,900 ✅ | vol_contraction: +$160 ✅
- gapfill: 14% WR, -$2,565 ❌ | vwapfade: 11% WR, -$2,750 ❌
- equal_tops_bottoms (PF 3.02, best strategy) NOT YET in live inference — high priority
- Feb 26: 100 trades in one day — possible overtrading under investigation

### Session Context Fix — Root Cause + Solution
- Root cause: daily memory file wasn't being read on session boot, causing Rob to repeat context daily
- Fix: BOOTSTRAP.md carries "Recent Changes" (rolling 48h summary). Key facts distilled to MEMORY.md.
- Protocol: at end of any session with significant changes, update BOOTSTRAP.md Recent Changes + distill to MEMORY.md

### Docs Purged of Stale Content
- EEP scoring: removed everywhere
- Opus: banned, removed everywhere. Sonnet=primary, Haiku=crons only
- IBKR/nq-bar-feed: retired, SMB is the live feed
- Port 8888 → 8892 for Blofin dashboard (everywhere)
- NQ Research Scientist: removed from AGENTS.md

## Ops Lessons (Feb 24, 2026)
- **Kanban discipline**: spawn → PATCH In Progress → update status.json — must happen atomically. Rob called this out.
- **Dispatch immediately**: don't wait for "ideal conditions" — when data supports a test, run it. Rob called out delay on ML exit re-run.
- **CPU spikes 85°C at 6 AM**: ambient temps + sustained multi-process load; transient, not persistent

## NQ Live Trading Architecture (Feb 24, 2026)

### ⛔ LIVE TRADING & PROP FIRM EVALS REQUIRE EXPLICIT ROB APPROVAL — NEVER ACTIVATE AUTONOMOUSLY
Never enable live trading, fire TradersPost webhooks, place real orders, or start any prop firm eval (Lucid, FTMO, etc.) without Rob explicitly saying "go live." This includes all future prop firm accounts.

### NQ Live Strategy: GOD MODEL
- NOT individual strategies (momentum, orb, etc.) — those are components
- The live model is a single unified "God Model" — best of all strategies combined into one
- Do not reference individual strategy PFs when discussing live trading readiness

### Final Architecture (locked)
```
DATA:       NinjaTrader (Windows 192.168.68.88) → SMB /mnt/nt_bridge/bars.csv (ET timestamps)
            → nq-smb-watcher.service converts ET→UTC, appends to NQ_continuous_1min.csv
            → God Model inference on every bar (DRY_RUN=True)

EXECUTION:  (Future, Rob approves) Signal engine → TradersPost webhook → Tradovate → Lucid prop accounts
            Webhook token in config_live.py (gitignored) — do NOT fire without Rob's approval
```

### Key Architecture Decisions
- **SMB feed is the live data source** — NinjaTrader writes bars.csv, we read it. Never write to it.
- **TradersPost is execution-only** — routes orders only, no data feed
- **Tradovate feed** — optional future upgrade, credentials not yet set up
- **signalPrice is MANDATORY** in TradersPost webhooks when using Tradovate broker

### Tradovate Credentials (needed for live feed — not yet provided)
- `TRADOVATE_CID`  — integer, from tradovate.com → Settings → Developer → API Keys
- `TRADOVATE_SEC`  — string, same location
- `TRADOVATE_USER` — Tradovate email
- `TRADOVATE_PASS` — Tradovate password
- Store in: `NQ-Trading-PIPELINE/config_live.py` (gitignored)
- Current live data feed is SMB (NinjaTrader) — Tradovate feed is optional future upgrade

### Services
- `nq-smb-watcher.service` — **ACTIVE LIVE FEED**. Reads `/mnt/nt_bridge/bars.csv`, converts ET→UTC, appends to `NQ_continuous_1min.csv`, runs God Model in DRY_RUN mode.
- `nq-dashboard.service` — Dashboard at port 8891
- `nq-bar-feed.service` — RETIRED (IB delayed feed, replaced by SMB watcher Feb 26)
- `nq-tradovate-feed.service` — DISABLED (optional future upgrade)

### Data File
- `processed_data/NQ_continuous_1min.csv` — 403K+ rows, Jan 2025→present, all UTC
- Schema: datetime(UTC ISO), open, high, low, close, volume, contract
- Contracts roll quarterly — next roll NQM6 March 13 2026

### Execution Details
- Lucid 100K Flex eval: max DD $3K, daily DD $2K, min 10 trades
- Top Phase 2 strategies ready: momentum PF 2.91, orb PF 2.92 (target_horizon=10), gap_fill PF 2.43
- TradersPost webhook fires: {ticker: "NQH6", action: "buy"/"sell"/"exit", signalPrice: float, stopLoss: {...}, takeProfit: {...}}
- Tradovate execution NOT through TradersPost for data — only for order routing on prop accounts

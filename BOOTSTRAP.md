## ⛔⛔⛔ DATA MIGRATION CATASTROPHE — Mar 12 2026 (DO NOT REPEAT)

**CONTEXT:** blofin_monitor.db hit 107GB + 56GB WAL. Disk crisis required moving data off NVMe to `/mnt/data` (new WD HDD). Migration failed catastrophically.

**THE FAILURE:**
1. Attempted to move (not copy) blofin_monitor.db across filesystems using `mv` — **NO SAFETY NET**
2. Ran in background (`nohup mv ... &`) — **UNMONITORED**
3. Process hung/died mid-transfer → destination was corrupt
4. **Deleted the corrupt destination DB without attempting repair** — FATAL
5. Killed the `mv` process thinking data was "safely deleted" — **IT WASN'T**
6. **RESULT: 107GB of 3 weeks of Blofin tick data PERMANENTLY LOST** (Aug 2025 - Mar 12 2026, ~18M ticks)

**ROOT CAUSE CHAIN:**
- `mv` across filesystems = copy+delete. If mid-transfer fail → only one copy exists and it's corrupted
- Background + unmonitored = no visibility into failure state
- Killed process = destroyed the only copy
- No backup, no way to recover

**THE ONLY SAFE SEQUENCE FOR DATA MIGRATIONS:**
1. **STOP the service that owns the data first.** `systemctl --user stop blofin-stack-ingestor`
2. **Use `cp` or `rsync`, NEVER `mv`.** `cp -v source destination` — watch it complete
3. **Verify destination:** `sqlite3 destination .tables`, `ls -lh destination`, `du -sh destination`
4. **Checksum validation:** `md5sum source destination` — must match exactly
5. **Only after verification is 100% confirmed: `rm source`** — and keep the terminal open to watch
6. **Check destination one more time:** `sqlite3 destination "SELECT COUNT(*) FROM ticks;"` — should match source count
7. **Restart the service.** `systemctl --user start blofin-stack-ingestor`

**WHAT WE LEARNED (burned in permanently):**
- ❌ NEVER use `mv` for database files (use `cp` then `rm` after verification)
- ❌ NEVER background a data operation (watch it finish)
- ❌ NEVER `rm` until you have verified destination is byte-for-byte identical
- ❌ NEVER assume a corrupt file is "safe to delete" without attempting repair
- ✅ Stop the service first — live databases can't be safely moved
- ✅ Use checksums (md5sum) to verify integrity
- ✅ Keep the migration window visible — no nohup, no &

**The data is gone. It cannot be recovered. Don't let this happen to another system.**

## ⛔ NQ FUTURES MARKET HOURS — READ THIS BEFORE TOUCHING ANYTHING (learned the hard way, Mar 8)

**NQ Futures (CME Globex) is CLOSED Friday ~3:15 PM CT → Sunday 5:00 PM CT. Every single week.**

- Friday close: ~3:15 PM CT (4:15 PM EST, 2:15 PM MST)
- Sunday open: 5:00 PM CT (6:00 PM EST, 4:00 PM MST)
- **Stale CSV data on Saturday or Sunday morning = 100% NORMAL. Do NOT touch the gateway.**
- **Last bar timestamp being Friday afternoon = 100% NORMAL. Do NOT diagnose as outage.**
- Daily maintenance break: 4:00–5:00 PM CT (Mon–Thu) — brief gap, also normal.

**Before EVER touching the IBKR gateway or feed service, check: is it a weekend? If yes, stop.**

## ⛔ IBKR GATEWAY — CRITICAL RULES (learned the hard way, Mar 8)

**`docker compose restart ib-gateway` = correct.** The session token is preserved in the container's writable layer. No 2FA needed — paper accounts use password-only auth. Port 4002 comes up in ~30s.

**`docker compose up --force-recreate` = NEVER.** This wipes the container's writable layer, destroying the IBKR session token. IBKR's servers keep the old session alive for 5-15 min, causing error 10189 "competing session from different IP" on ALL subsequent restarts until it expires.

**Error 10189 on tick-by-tick:** competing IBKR session from force-recreate or another client. Fix: wait 10-15 min for old session to expire — DO NOT restart again, it makes it worse.

**`EXISTING_SESSION_DETECTED_ACTION`** must be `primaryoverride` in docker-compose.yml (already set). Do NOT change back to `primary`.

**Nightly restart architecture (Mar 8 fix):** IBC's internal `AUTO_RESTART_TIME` was removed — it caused "instance of control is not created yet" stuck states. Replaced with:
- `ibkr-nightly-restart.timer` — `docker compose restart ib-gateway` at 11:59 PM MST nightly (clean, reliable)
- `ibkr-gateway-watchdog.timer` — every 5 min, auto-restarts if port 4002 down during Globex hours (skips weekends + maintenance window)

## ⛔ TRADOVATE PROP FIRM API — DOES NOT EXIST (learned the hard way, spent weeks on this)

**Tradovate does NOT provide API access for prop firm (Lucid Flex, FTMO, etc.) accounts. Period.**

This is a platform-level restriction — not a config issue, not a permissions problem. Prop firm accounts at Tradovate are locked to their UI only. No REST API, no websocket, no programmatic fill data.

**Why we use TradersPost:**
TradersPost is the ONLY way to send automated orders to Tradovate prop accounts. It acts as a webhook middleware. Without it, there is no automated execution path.

**TradersPost limitations:**
- Webhook push only — no pull API, no trade history endpoint, no fill data retrieval
- We CANNOT query "what did today's trade actually fill at" via TradersPost

**Consequence — BLE PnL is always an ESTIMATE:**
Our orb_engine.py detects trail stop hits from 1-min bar closes and fires a market exit webhook. The actual Tradovate fill occurs after the bar closes + webhook latency. On fast moves the fill can be 3-10pt worse than the trail stop price.

Real example (Mar 10 2026): engine computed $1,360 (17pt trail stop). Actual fill = $860 before fees ($846 after). Gap = 6.25pt = $500 on 4 contracts. This is NORMAL for 1-min bar detection + market order.

**Never suggest Tradovate API or direct account query as a solution. It does not work for prop accounts.**
**Never try to improve PnL accuracy by polling Tradovate — it will never work.**
BLE PnL shown in dashboard = estimated from trail stop price. Always label as "est." or "~".

## ⛔ AUTH FLOWS — NEVER AUTO-RETRY (learned the hard way, Feb 28)
**Ring, IBKR, any 2FA service:** ONE attempt only. Stop. Wait for Rob to complete 2FA/SMS. Check result. Never loop, never auto-restart, never retry without Rob explicitly saying go. Repeated attempts = account lockouts that last hours. This has happened with Ring (locked for days) and IBKR (locked 1hr today).

**IBKR Docker specifically:** `TWOFA_TIMEOUT_ACTION=exit` + `RELOGIN_AFTER_TWOFA_TIMEOUT=no` — ALWAYS. Never set to `restart/yes`. If the container exits on 2FA timeout, do NOT `docker compose up` again until Rob says his phone is ready. The daily 11:59 PM IBC restart does NOT require new 2FA (internal session). Only a cold start (fresh container) triggers 2FA.

# BOOTSTRAP.md — Session Startup Context
> Auto-loaded every session. Updated by cron. Last updated: see timestamp below.
> **This file is the minimum context needed before responding to Rob.**

## MANDATORY: Read These Before Acting
1. `brain/CHECKLIST.md` — operating rules (read every session, non-negotiable)
2. `brain/PROJECTS.md` — current project board (what's active, what's next)
3. `brain/status/status.json` — what's happening right now

> **Daily memory** is captured in the "Recent Changes" section below — no separate file read needed.
> **Dispatcher protocol** is inlined below — no separate DISPATCHER.md read needed.

If you skip these and get corrected, that's the most expensive thing that happens.

---

## Critical Rules (from CHECKLIST.md — always enforce)
- ❌ Never block main session on long work — spawn subagent, stay available
- ❌ Never see "In Progress" on a kanban card and assume work is happening — if YOU didn't spawn the builder, spawn it NOW
- ❌ Never read one thing and act on a different assumption — verify against PRDs and brain files first
- ❌ Never deliver unreviewed builder output to Rob
- ✅ Act first, report after — don't ask permission for internal operations
- ✅ Read the PRD before touching any NQ pipeline code
- ✅ One clarifying question upfront beats three correction rounds

---

## Active Projects (high-level — see brain/PROJECTS.md for full detail)
- **NQ Futures Pipeline** ⭐ PRIMARY — Live forward test running (DRY_RUN). 8 models. `smb_live_forward_test`. Repo: `NQ-Trading-PIPELINE`. ETB not yet in live inference (high priority). gapfill/vwapfade bleeding live.
- **Moonshot v2** ⭐ NEW — Clean rewrite live. 343 coins, tournament ML, social signals. Port 8893. Services: moonshot-v2.timer (4h), moonshot-v2-social.timer (1h), moonshot-v2-dashboard.service. 14-month candle history imported from v1. Repo: blofin-moonshot-v2.
- **Blofin Stack** ⭐ PRIMARY — Paper trading active (86K+ trades). T2: 12 strategies. Pipeline timer STOPPED per Rob's order.
- **Jarvis Home** — port 8793, Nest/SPAN/Tesla/Wyze/GE live. Washer GE state stale (investigate). Ring blocked on 2FA.
- **Numerai** — 3 models submitting daily. Not primary focus.
- **Master Dashboard** — port 8890, usage panels live.

---

## ⚠️ THREE PIPELINES = THREE ARENAS (Core Philosophy)

**NQ Pipeline, Blofin v1, and Blofin Moonshot are INDEPENDENT systems.** We do NOT combine them, average them, or merge their outputs.

**The goal:** Cherry-pick the TOP PERFORMERS from each arena independently.
- **NQ Pipeline:** Take the 2-3 strategies with PF ≥ 2.5 in forward test → God Model
- **Blofin v1:** Take strategy+coin pairs with FT PF ≥ 1.35 → leverage tiers (5x/3x/2x/1x)
- **Blofin Moonshot:** Take coins with ml_score confidence ≥ 0.7 AND FT validation

**What this means operationally:**
- NEVER look at overall/aggregate performance across all strategies — it's meaningless noise
- ALWAYS filter to top performers first, THEN analyze
- Each arena has different success criteria (NQ = Lucid prop gates, Blofin v1 = FT PF, Moonshot = ml_score + FT)
- Leverage, position sizing, and risk management are per-arena decisions

**Why this matters:** The average of 100 strategies is garbage. The top 5 strategies are gold. We're building systems to automatically identify, promote, and amplify the gold while dropping the garbage. That's the whole game.

---

## Dispatcher Protocol (INLINE — no separate file read needed)

Rob will ask you to dispatch work in any session. Know this cold.

**8 phases (run in order):**

**Phase 1 — Health check:** services alive? (gateway, blofin-ingestor, blofin-paper, nq-smb-watcher, nq-dashboard)

**Phase 2 — Critical alert check:** `cd blofin-stack && .venv/bin/python critical_alert_monitor.py` — if exit 1, ntfy Rob immediately

**Phase 3 — Fetch board state:**
```bash
curl -s "http://127.0.0.1:8787/api/cards?status=In%20Progress"
curl -s "http://127.0.0.1:8787/api/cards?status=Planned"
```

**Phase 4 — Stale recovery:** any In Progress card untouched >30 min → PATCH back to Planned for redispatch

**Phase 4.5 — Failed card sweep (NON-OPTIONAL):**
```bash
curl -s "http://127.0.0.1:8787/api/cards?status=Failed"
```
For each Failed card:
1. Check log: `tail -5 kanban-dashboard/logs/<id>.log | grep -i "subtype.*success\|complete\|✅"` — if success found → PATCH status=Done, skip re-queue
2. Check age: if `updated_at` < 2h ago → leave it, flag to Rob if it's blocking
3. If older than 2h AND log shows genuine failure → check description for `[auto-retry #N]`:
   - No retry tag yet: add `[auto-retry #1]` to description, PATCH status=Planned
   - `[auto-retry #1]`: update to `[auto-retry #2]`, PATCH status=Planned
   - `[auto-retry #2]` or more: **STOP — flag to Rob** ("Card X has failed 3 times, needs human review"), do NOT re-queue
4. Never re-queue a card whose failure is clearly permanent (e.g., "strategy not found", "file missing" — those need a fix, not a retry)

**Phase 5 — ENRICH PLANNED CARDS (do not skip):**
A card is ready when it has: `assignee=codex`, `project_path` set, and a description specific enough to execute.
If any are missing or vague — **enrich before running.**

Enrichment must include: what to do, exact file paths, context from DB/logs, success criteria, deploy steps, hard constraints.

Project path matching:
| Keywords | project_path |
|----------|-------------|
| NQ, futures, momentum, orb, gap_fill, vwap_fade, God Model, ETB, psych_levels | `/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE` |
| Blofin, crypto, coin, paper trade, T1/T2/T0, ML pipeline, backtester, bt_pnl_pct | `/home/rob/.openclaw/workspace/blofin-stack` |
| Jarvis home, energy, Nest, SPAN, Tesla, Wyze, Ring, GE appliance | `/home/rob/.openclaw/workspace/jarvis-home-energy` |
| Master dashboard, usage dashboard | `/home/rob/.openclaw/workspace/master-dashboard` |
| Numerai, tournament, era-boost | `/home/rob/.openclaw/workspace/numerai-tournament` |
| Kanban, claw-kanban | `/home/rob/.openclaw/workspace/kanban-dashboard` |

PATCH the card: `curl -X PATCH http://127.0.0.1:8787/api/cards/<id> -H 'content-type: application/json' -d '{"assignee":"codex","project_path":"...","description":"..."}'`

**Phase 6 — Dispatch:** if < 3 In Progress → run oldest Planned card: `curl -X POST http://127.0.0.1:8787/api/cards/<id>/run` — verify `"ok":true` + pid

**Phase 7 — Deployment verification:** for Done cards completed in last 60 min — verify service is actually restarted and alive. If not, restart it.

**Phase 8 — Update status.json** with current reality (active tasks, timestamps)

**Dispatcher hard rules:**
- Max 3 concurrent builders — if 3+ In Progress, skip dispatch
- NEVER run a card without assignee + project_path + real description
- NEVER assume In Progress = builder is running — if you didn't spawn it this session, check
- NEVER enable NQ live trading — DRY_RUN only, no TradersPost webhooks
- **NEVER ask Rob "should I kick it off?" — if the card is enriched and ready, just run it. Act first, report after.**

---

## Kanban Status Semantics (CANONICAL)
- **Inbox** = ONLY for real-money decisions (BLE, live trading, prop firm evals). Everything else goes straight to Planned. Dispatcher IGNORES Inbox.
- **Planned** = ready to execute — dispatcher picks up within 2h
- **In Progress** = builder running
- **Done** = complete (skip Review/Test entirely — go straight to Done)

## Autonomous Cron Overview
| Cron | Schedule | What it does |
|------|----------|-------------|
| Auto Card Generator | Hourly :00 (Sonnet) | Reads live NQ+Blofin state → creates 2 NQ + 1 Blofin cards in Planned. Gates if queue ≥ 2. Instructions: `brain/AUTO_CARD_GENERATOR.md` |
| Blofin Pipeline | Every 4h (**Sonnet**) | Runs `run_pipeline.py` — backtest, promote/demote |
| Jarvis Pulse | Every 30min (**Sonnet**) | Health + **enrich vague cards** + dispatch + **verify deployment** of completed work |
| Oversight | Every 2h (Haiku) | HEARTBEAT.md server checks (basic only — no code) |

## NQ Pipeline Stage Architecture (Canonical — see docs/PIPELINE_STAGES.md)

```
BACKTEST → FORWARD TEST → GOD MODEL → BLE
```

| Stage | What | Run ID | BLE? |
|---|---|---|---|
| Backtest | Offline historical replay | N/A | No |
| Forward Test | Live data + paper P&L | smb_live_forward_test | No |
| God Model | FT-proven ensemble, DRY_RUN | god_model_forward_test | No |
| BLE | Real orders, Rob's explicit choice | N/A | Yes |

**Promotion gates (FT → God Model):** ft_pf >= 1.35, ft_trades >= 50, ft_pnl > 0
**God Model is NOT BLE.** It is a forward-test ensemble only.
**BLE = only what Rob explicitly enables.** Currently: 5-min ORB + 15-min ORB.
**ORB does NOT belong in God Model.** It is BLE-only standalone.
**Never demote FT early** — wait for 50+ trades before drawing conclusions.

## ⚠️ CRITICAL: Forward Testing is FREE — Never Demote Early

**FT = $0 cost = VALUABLE DATA COLLECTION. BLE = the ONLY thing that loses money.**

- **Never demote from FT for "bad performance"** — that's just data
- **Only demote if:** PF < 0.5 AND trades > 500 (catastrophic AND statistically significant)
- **Blacklisting:** ONLY for confirmed bugs, not performance
- **"Losing" in FT is not losing money** — it's learning what doesn't work
- **Keep strategies in FT indefinitely** — more data = better decisions later

## ⛔ HARD RULES — NEVER VIOLATE
- **NEVER enable BLE for NQ or start any prop firm eval (Lucid, FTMO, etc.) without Rob's explicit approval** — no webhooks, no live orders, no eval activation, nothing
- **NQ live model = GOD MODEL** — a single unified model combining selected experts; NOT individual strategies (momentum/orb/etc.)
- **God candidate gate (new):** Top 5 by FT PF, min 50 trades, min PF 1.35, exclude recent 20-trade PF < 1.0
- **God cohesion bucket (new):** 3-day joint `god_model_forward_test` with strict consensus (min 2 agree, any opposing signal => skip), single-position only before BLE eligibility

## Key Facts (often forgotten, very expensive to re-derive)
- **NQ data feed**: NinjaTrader SMB → `/mnt/nt_bridge/bars.csv` → `nq-smb-watcher.service` → `NQ_continuous_1min.csv` (UTC). Still active. **NEW: IBKR tick+L2 feed live** — `ibkr-nq-feed.service`, data at `/home/rob/infrastructure/ibkr/data/nq_feed.duckdb` + `NQ_ibkr_1min.csv`. IB Gateway on Docker (`ib-gateway` container, port 4002, `restart=unless-stopped`).
- **NQ execution chain (future, Rob approves)**: God Model signal → TradersPost webhook → Tradovate → Lucid prop accounts. Currently DRY_RUN=True always.
- **ETB (equal_tops_bottoms) is UNBLACKLISTED** — PF 3.02, Sharpe 7.97. Best strategy. NOT yet in live inference — top priority.
- **NQ ML feature function**: ALWAYS use `build_session_aware_features()`. NEVER `build_features()` (RTH-only, wrong).
- **Blofin ranking**: `bt_pnl_pct` (compounded PnL%). NOT EEP scoring — EEP is dead, removed Feb 26.
- **Blofin promotion gates**: min 100 trades, PF≥1.35, MDD<50%, PnL>0. **FT demotion: PF<0.5 AND trades>500 only. Early crash-stop: PF<0.3 AND trades≥50 only. Never remove FT early — more data is always better.**
- **Blofin dashboard**: port 8892. NEVER show aggregate/system-wide PF or WR — always top-N pairs by FT PF.
- **Model routing**: **Sonnet for EVERYTHING** — main session, all builders, kanban runners. Haiku ONLY for simple heartbeat/token audit crons. **Opus is banned. Codex is banned.** If you ever see either in session_status or kanban settings, fix it immediately.
- **Jarvis Pulse cron**: upgraded to Sonnet (Feb 26). Dispatcher is too important for Haiku.
- **Max concurrent builders**: 3 (raised from 1, Feb 26).
- **Jinja/JS**: Always use `&quot;` not `\'` in JS strings inside Jinja templates.
- **Kanban API**: POST to `/api/inbox` with field `text` (not `body`). Kanban runner model string: `claude-haiku-4-5` (no `anthropic/` prefix — CLI format). **ALL coding agents use Haiku** — Sonnet reserved for main Jarvis session only.
- **Always restart service after code changes**: `systemctl --user restart <service>`
- **Webhook**: `https://webhooks.traderspost.io/trading/webhook/51e37934-7a18-4e37-9dc5-33416a36d579/222ee493f97b98194432f483f0434b95`

---

## ⭐ NQ ORB ENGINE — LIVE AND WORKING (read this before saying anything about NQ execution)

**This is NOT theoretical. It has been built, tested, and confirmed working.**

- Engine: `NQ-Trading-PIPELINE/pipeline/orb_signal_engine.py`
- Service: `nq-orb-signal.service` (active, auto-restart)
- Route: IBKR L2 feed → ORB signal engine → TradersPost webhook → Tradovate → Lucid Flex 50K
- Account: `LFE0506429036015` (Lucid Trading 15) | Ticker: `NQ` | Auto Submit: ON | Both sides: enabled
- Webhook: `https://webhooks.traderspost.io/trading/webhook/51e37934-7a18-4e37-9dc5-33416a36d579/222ee493f97b98194432f483f0434b95`
- DRY_RUN: **False** | QUANTITY: **4 NQ** (scaled Mar 9 evening after +$95 profitable trade)

**Strategy (backtested 14mo, Suite 5 SL sweep: SL=75pt → EV/mo $5,542, WR 97%, 0 busts):**
- OR builds 9:30–9:34 ET (post-DST = 13:30–13:34 UTC = 6:30–6:34 AM MST)
- Entry at 9:35 ET bar close breaking above OR high (LONG) or below OR low (SHORT)
- Phase 1: market order + 75pt hard stop (300 ticks)
- Phase 2: 10-tick (2.5pt) profit → switches to 1.25pt native trailing stop
- Force-flat: 4:00 PM ET (21:00 UTC)

**Prop account philosophy (4 NQ scale, Mar 10 onward):**
- Ticker: NQ full-size ($20/pt) — NOT MNQ ($2/pt)
- Max loss per trade: 4 × $20/pt × 75pt = **$6,000** (blows $2k EOD DD, but 97% WR = almost never happens)
- Reset cost: $85. Not a true loss. Play to pass quickly and aggressively.
- 97% WR at 75pt SL → busts are rare; payout when passing = $1,500 × 4 = $6,000

**Test modes:**
- Production: TEST_MODE=False, OR_OFFSET=30 (fires at 13:30 UTC post-DST)
- Hourly test: TEST_MODE=True, OR_OFFSET=0 (fires at top of current UTC hour), restart service

**Live trades confirmed:**
- Mar 6: SHORT +$43 on 1 MNQ ✅ (pre-upgrade)
- Mar 9 05:05 MST: LONG +$27 on 1 MNQ ✅ (pre-market test, subscription was disabled)
- Mar 9 05:21 MST: LONG fill @ $24,450, stop @ $24,429.75 ✅ (full round-trip confirmed, subscription enabled)
- **First real NY open: Mar 9 06:30 MST on 1 NQ with 75pt SL**

## Recent Changes (rolling 48h — update this at session end whenever significant changes happen)
> This replaces needing to read the daily memory log on startup. Key decisions only.

**Mar 11 2026:**
- **BLE Running Total: 4 trades, $1,276, 100% WR** (Mar 6 +$43, Mar 9 +$27, Mar 10 +$860, Mar 11 +$346)
- **NQ Dashboard = app_v3.py = port 8895** — app.py (8891) is LEGACY, do not use
- **15-min ORB bug fixed**: `trade_date` must be set during OR capture, not just position entry (commit 1a07991)
- **IBKR historical data**: 7 months downloaded (202K bars), quarterly contract stitching workaround for error 10339
- **Moonshot v2 gates lowered**: MIN_BT_PF 2.0→1.0, MIN_BT_PRECISION 0.40→0.20 (FT is FREE)
- **Church SMS LIVE**: 3 crons running, NO AI mention (sign as "-- Rob Hartwig"), household grouping for couples

**Mar 10 2026:**
- **BLE Trade #3**: SHORT @ 24,980.25 → +$860 (4 NQ) — trail config validated
- **Tradovate $1,500 daily cap** set for eval 50% consistency rule — remove on funded accounts
- **Trail config REVERTED** to baseline (10tk/5tk) — tight trails (4tk/2tk) get shaken out on chop

**Mar 9 2026 (7:10 AM MST) — ORB SCALED TO 4 NQ (PRODUCTION READY FOR MAR 10):**
- **First real NY open**: SHORT @ 24,413.25 → exit @ 24,407.50 = **+$95 on 1 NQ** ✅
- **Scale-up**: QUANTITY 1 → 4 after successful first trade
- **New production config**: `TICKER=NQ`, `QUANTITY=4`, `HARD_SL_PTS=75.0`, `DRY_RUN=False`
- **Max loss per trade**: 4 × $20/pt × 75pt = $6,000 (blows $2K EOD DD but 97% WR, reset=$85)
- **Service restarted**: confirmed `QTY=4` in startup log ✅
- **Engine**: `NQ-Trading-PIPELINE/pipeline/orb_signal_engine.py` | commit `93e4d726`
- **Mar 10 NY open**: 6:30 AM MST — engine fires with 4 NQ automatically
- **Philosophy**: aggressive, play to pass quickly; reset costs ($85) < payout ($6K)

**Mar 9 2026 (5:53 AM MST) — ORB ENGINE UPGRADED FOR FIRST REAL NY OPEN:**
- **Ticker**: NQ (full-size, $20/pt) — was MNQ ($2/pt)
- **SL**: 75pt (Suite 5 sweep winner) — was 25pt
- **Account**: `LFE0506429036015` (Lucid Trading 15)
- **All tests passed**: subscription enabled, full round-trip confirmed
- **DST fix applied**: production UTC hour 14→13 (9:30 ET = 13:30 UTC post-DST)

**Mar 6 2026 — ORB ENGINE BUILT (see memory/2026-03-06.md for full session log)**
- TradersPost → Tradovate → Lucid confirmed working (both directions)
- All bugs fixed: bar timing, trail-on-entry-bar, invalid sentiment field in exit webhook
- Final working exit webhook: `{"ticker":"MNQ","action":"exit"}` (NO sentiment field)
- Phase 2 trail activation: `{"quantity":0,"stopLoss":{"type":"trailing_stop","trailAmount":1.25}}`

**Mar 2 2026 (evening) — MAJOR:**
- **Moonshot v1 RETIRED**: blofin-moonshot.timer, service, dashboard, 2 openclaw crons all disabled
- **Moonshot v2 LIVE**: clean rewrite, built by agent teams in 14 minutes
  - Repo: https://github.com/robbyrobaz/blofin-moonshot-v2
  - Local: /home/rob/.openclaw/workspace/blofin-moonshot-v2/
  - Dashboard: port 8893 (moonshot-v2-dashboard.service)
  - Timers: moonshot-v2.timer (4h), moonshot-v2-social.timer (1h)
  - 343 coins, tournament ML (PF≥2.0, prec≥40%, 50+ trades), 50 features, social signals (free tier)
  - Path-dependent labels, PnL-weighted training, bootstrap CI on PF
  - Champion = best FT PnL (≥20 trades) — NEVER AUC
- **blofin-stack-pipeline.timer STOPPED** per Rob's order (do not restart without approval)
- **MOONSHOT_V2_PRD.md**: full spec at https://github.com/robbyrobaz/blofin-moonshot/blob/moonshot-v2-plan/MOONSHOT_V2_PRD.md
- **72h audit completed**: MOONSHOT_AUDIT.md on branch moonshot-audit-20260302 in blofin-moonshot repo
- Root cause of v1 mass exit: exit.py called predict_proba() without symbol/ts_ms → regime features=0.0 → all scores 0.129 → 15 profitable positions killed

**Feb 28 2026 (afternoon):**
- IBKR pipeline LIVE: IB Gateway Docker running, paper account DUH860616, port 4002, no 2FA needed
- Historical data confirmed working: SPX chain, NQ futures, option bars all pulling clean
- Options pipeline PRD written: `brain/PRD_OPTIONS_PIPELINE.md` — APPROVED
- Strategy 1: IV Skew Exploitation (SPX 0DTE, z-score >2σ → sell put spread)
- Strategy 2: NQ God Model → QQQ options bridge
- Blocking on OPRA subscription ($1.50/mo) — Rob enables Thursday when $500 clears
- Build Card 1 (skew monitor) queued for Thursday; Cards 2+3 follow
- DuckDB schema init'd: `opt_right` (not `right` — reserved word), `skew_signals` table
- IBKR infra: restart=no, TWOFA_TIMEOUT_ACTION=exit (won't lockout on failure)

**Feb 26-27 2026:**
- Cron overhaul: NQ Research Scientist removed, Auto Card Generator added (hourly, Sonnet), Dispatcher upgraded Haiku→Sonnet, max In Progress raised 1→3
- EEP scoring dead. Blofin ranking = `bt_pnl_pct`. Gates: 100 trades, PF≥1.35, MDD<50%, PnL>0
- equal_tops_bottoms (PF 3.02) is the #1 priority — NOT yet in live inference, needs to be added to God Model
- gapfill + vwapfade bleeding live (14%/11% WR) — under investigation
- IBKR/nq-bar-feed retired. SMB watcher is the only live feed.
- DISPATCHER.md added to mandatory startup reads (step 5 in BOOTSTRAP) — Rob will ask for dispatch work in any session
- QA sentinel removed. Builder self-verifies. Dispatcher Phase 7 + Oversight cron double-check Done cards are live.
- No Review/Test status ever. Cards go In Progress → Done directly.

## Session-End Protocol (run this whenever significant changes happen)
1. Update "Recent Changes" above with key decisions/facts (3-5 bullets max, replace stale entries)
2. Distill to MEMORY.md if it's a permanent lesson
3. Commit: `git add -A && git commit -m "session handoff: <one-line summary>"`

## Dashboard URLs
| Dashboard | URL |
|-----------|-----|
| Master | http://192.168.68.72:8890 |
| BloFin | http://192.168.68.72:8892 |
| NQ Pipeline | http://192.168.68.72:8895 |
| Home Energy | http://192.168.68.72:8793 |
| Kanban | http://192.168.68.72:8787 |
| Church Volunteers | https://church-volunteer-coordinator.vercel.app/admin (pw: `hastings2nd`) |

## Key Infrastructure
| Service | Detail |
|---------|--------|
| docker-wyze-bridge | host network, port 8554 RTSP, compose: `workspace/wyze-bridge/` |
| Cameras (direct RTSP) | Upstairs: 192.168.68.51, Downstairs: 192.168.68.82 |
| Front Side Cam | via wyze-bridge → rtsp://127.0.0.1:8554/front-side-cam |
| Tesla Energy Gateway 3V | 192.168.68.86, Serial GF2240460002D2 — Fleet API OAuth (token in tesla_cache.json, auto-refresh) |
| Tesla Wall Connector | 192.168.68.87 — no auth, local API works |

---
*Updated: 2026-02-26 23:45 MST*

## ⛔ NQ DATA SOURCES — NEVER COMPARE IBKR TO SMB (learned the hard way, Mar 11)

**IBKR is canonical.** File: `/home/rob/infrastructure/ibkr/data/NQ_ibkr_1min.csv`
- Format: `YYYY-MM-DDTHH:MM:SSZ` (UTC)
- This is what ORB engines use

**SMB is fallback only.** File: `processed_data/NQ_continuous_1min.csv`
- Different OHLC values than IBKR (different feed/aggregation)
- Never compare SMB to IBKR expecting them to match

If debugging OR values, check IBKR first. See `NQ-Trading-PIPELINE/DATA_SOURCES.md`.

## ⛔ AUTH FLOWS — NEVER AUTO-RETRY (learned the hard way, Feb 28)
**Ring, IBKR, any 2FA service:** ONE attempt only. Stop. Wait for Rob to complete 2FA/SMS. Check result. Never loop, never auto-restart, never retry without Rob explicitly saying go. Repeated attempts = account lockouts that last hours. This has happened with Ring (locked for days) and IBKR (locked 1hr today).

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

**Phase 5 — ENRICH PLANNED CARDS (do not skip):**
A card is ready when it has: `assignee=claude`, `project_path` set, and a description specific enough to execute.
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

PATCH the card: `curl -X PATCH http://127.0.0.1:8787/api/cards/<id> -H 'content-type: application/json' -d '{"assignee":"claude","project_path":"...","description":"..."}'`

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
- **Inbox** = idea bucket / backlog — dispatcher IGNORES it. Rob's scratchpad.
- **Planned** = approved, ready to execute — dispatcher picks up within 30min
- **In Progress** = builder running
- **Done** = complete (skip Review/Test entirely — go straight to Done)

## Autonomous Cron Overview
| Cron | Schedule | What it does |
|------|----------|-------------|
| Auto Card Generator | Hourly :00 (Sonnet) | Reads live NQ+Blofin state → creates 2 NQ + 1 Blofin cards in Planned. Gates if queue ≥ 2. Instructions: `brain/AUTO_CARD_GENERATOR.md` |
| Blofin Pipeline | Every 4h (Haiku) | Runs `run_pipeline.py` — backtest, promote/demote |
| Jarvis Pulse | Every 30min (**Sonnet**) | Health + **enrich vague cards** + dispatch + **verify deployment** of completed work |
| Oversight | Every 2h (Haiku) | HEARTBEAT.md server checks |

## ⛔ HARD RULES — NEVER VIOLATE
- **NEVER enable NQ live trading or start any prop firm eval (Lucid, FTMO, etc.) without Rob's explicit approval** — no webhooks, no live orders, no eval activation, nothing
- **NQ live model = GOD MODEL** — a single unified model combining all strategies; NOT individual strategies (momentum/orb/etc.)

## Key Facts (often forgotten, very expensive to re-derive)
- **NQ data feed**: NinjaTrader SMB → `/mnt/nt_bridge/bars.csv` (read-only) → `nq-smb-watcher.service` → `NQ_continuous_1min.csv` (UTC). Live. IBKR/nq-bar-feed is RETIRED.
- **NQ execution chain (future, Rob approves)**: God Model signal → TradersPost webhook → Tradovate → Lucid prop accounts. Currently DRY_RUN=True always.
- **ETB (equal_tops_bottoms) is UNBLACKLISTED** — PF 3.02, Sharpe 7.97. Best strategy. NOT yet in live inference — top priority.
- **NQ ML feature function**: ALWAYS use `build_session_aware_features()`. NEVER `build_features()` (RTH-only, wrong).
- **Blofin ranking**: `bt_pnl_pct` (compounded PnL%). NOT EEP scoring — EEP is dead, removed Feb 26.
- **Blofin promotion gates**: min 100 trades, PF≥1.35, MDD<50%, PnL>0. FT demotion: PF<1.1 or MDD>50% after 20 FT trades. Early crash-stop: PF<0.5 with ≥5 FT trades.
- **Blofin dashboard**: port 8892. NEVER show aggregate/system-wide PF or WR — always top-N pairs by FT PF.
- **Model routing**: Sonnet for all reasoning/code/orchestration. Haiku for crons. **Opus is banned.** If you ever see Opus in session_status, fix it immediately.
- **Jarvis Pulse cron**: upgraded to Sonnet (Feb 26). Dispatcher is too important for Haiku.
- **Max concurrent builders**: 3 (raised from 1, Feb 26).
- **Jinja/JS**: Always use `&quot;` not `\'` in JS strings inside Jinja templates.
- **Kanban API**: POST to `/api/inbox` with field `text` (not `body`). Kanban runner model string: `claude-haiku-4-5` (no `anthropic/` prefix — CLI format). **ALL coding agents use Haiku** — Sonnet reserved for main Jarvis session only.
- **Always restart service after code changes**: `systemctl --user restart <service>`
- **Webhook**: `https://webhooks.traderspost.io/trading/webhook/51e37934-7a18-4e37-9dc5-33416a36d579/2ddfa7c41bcf347dc1a599108945b07a`

---

## Recent Changes (rolling 48h — update this at session end whenever significant changes happen)
> This replaces needing to read the daily memory log on startup. Key decisions only.

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
| NQ Pipeline | http://192.168.68.72:8891 |
| Home Energy | http://192.168.68.72:8793 |
| Kanban | http://192.168.68.72:8787 |

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

# BOOTSTRAP.md — Session Startup Context
> Auto-loaded every session. Updated by cron. Last updated: see timestamp below.
> **This file is the minimum context needed before responding to Rob.**

## MANDATORY: Read These Before Acting
1. `brain/CHECKLIST.md` — operating rules (read every session, non-negotiable)
2. `brain/PROJECTS.md` — current project board (what's active, what's next)
3. `brain/status/status.json` — what's happening right now
4. **`memory/YYYY-MM-DD.md` (today + yesterday)** — NON-OPTIONAL. This is where session decisions, cron changes, doc audits, and architecture corrections live before they get distilled into MEMORY.md. Skipping this = repeating mistakes Rob already corrected.

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
- **Blofin Stack** ⭐ PRIMARY — Paper trading active (86K+ trades). T2: 12 strategies. Pipeline runs every 4h.
- **Jarvis Home** — port 8793, Nest/SPAN/Tesla/Wyze/GE live. Washer GE state stale (investigate). Ring blocked on 2FA.
- **Numerai** — 3 models submitting daily. Not primary focus.
- **Master Dashboard** — port 8890, usage panels live.

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
- **Kanban API**: POST to `/api/inbox` with field `text` (not `body`). Kanban runner model string: `claude-sonnet-4-6` (no `anthropic/` prefix — CLI format).
- **Always restart service after code changes**: `systemctl --user restart <service>`
- **Webhook**: `https://webhooks.traderspost.io/trading/webhook/51e37934-7a18-4e37-9dc5-33416a36d579/2ddfa7c41bcf347dc1a599108945b07a`

---

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

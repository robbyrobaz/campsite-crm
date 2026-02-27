# BOOTSTRAP.md — Session Startup Context
> Auto-loaded every session. Updated by cron. Last updated: see timestamp below.
> **This file is the minimum context needed before responding to Rob.**

## MANDATORY: Read These Before Acting
1. `brain/CHECKLIST.md` — operating rules (read every session, non-negotiable)
2. `brain/PROJECTS.md` — current project board (what's active, what's next)
3. `brain/status/status.json` — what's happening right now
4. `memory/YYYY-MM-DD.md` (today + yesterday) — recent context and decisions

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
- **NQ data feed**: NinjaTrader (Windows, 192.168.68.88) → SMB share `/mnt/nt_bridge/bars.csv` → `nq-smb-watcher.service` → `NQ_continuous_1min.csv`. Live and running as of Feb 26.
- **NQ execution chain**: Signal engine → TradersPost webhook → Tradovate/Lucid prop accounts (execution). NOT IBKR for live trading. NOT TradersPost for data.
- **Windows setup**: Python ML → NinjaTrader directly. TradersPost has NEVER been tested.
- **Start with MNQ** (not NQ) for initial live validation — 1/10th size, $2/pt
- **ETB (equal_tops_bottoms) is UNBLACKLISTED (Feb 26 2026)** — blacklist was wrong. 10/10 WF folds pass prop sim, PF 2.78–3.27, Sharpe 7.3–8.6, ~2000+ OOS trades per fold. This is one of the strongest strategies. ML feature research card in progress to find best entry conditions.
- **Jinja/JS**: Always use `&quot;` not `\'` in JS strings inside Jinja templates
- **Token reset**: March 1, 4:00 PM MST. **Sonnet is the highest model for EVERYTHING. Opus is banned.** Gateway config: primary=sonnet, fallback=haiku. If you ever see Opus in session_status, fix it immediately.
- **Webhook**: `https://webhooks.traderspost.io/trading/webhook/51e37934-7a18-4e37-9dc5-33416a36d579/2ddfa7c41bcf347dc1a599108945b07a`
- **Kanban API**: POST to `/api/inbox` with field `text` (not `body`)
- **Always restart service after code changes**: `systemctl --user restart <service>`

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
*Updated: 2026-02-24 17:07 MST*

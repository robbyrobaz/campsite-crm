# MEMORY.md — Jarvis COO Learnings & Reference

> Domain-specific knowledge lives with domain agents. This file is for COO-level lessons, preferences, and cross-cutting reference only.
> NQ details → NQ Agent (`agent:nq:main`)
> Crypto/Moonshot details → Crypto Agent (`agent:crypto:main`)
> Church details → Church Agent (`agent:church:main`)

## Model Routing (Updated Mar 16 2026)

- Subscription: Claude Max 20x ($200/mo flat). 7-day Sonnet limit is the binding constraint.
- **Current routing:** Opus for main Jarvis session. Nemotron-3-super-120b-a12b for builders. Haiku for crons.
- Gateway config: `~/.openclaw/openclaw.json` → `.agents.defaults.model.primary`
- Kanban runner model: `claude-haiku-4-5` (CLI format, no `anthropic/` prefix)

## Three Pipelines Philosophy (Core Architecture)

**NQ Pipeline, Blofin Stack, and Moonshot v2 are THREE INDEPENDENT ARENAS.** Never combine outputs.
- **NQ Pipeline** → NQ Agent owns
- **Blofin Stack** → Crypto Agent owns
- **Moonshot v2** → Crypto Agent owns

**Rob's directive (Mar 15):** FT is FREE. Expect 95% losers. Only track top performers. Never report aggregate metrics.

## Hyperliquid S&P 500 Pipeline (Mar 20 2026 — LIVE) → SP Agent Owns This

- **Repo:** `robbyrobaz/hyperliquid-sp500-pipeline`
- **Contract:** `xyz:SP500` on Trade[XYZ] perp dex (Hyperliquid L1)
- **Leverage:** 50x max (isolated margin only)
- **API:** POST `https://api.hyperliquid.xyz/info` with `"dex":"xyz"` — THIS IS CRITICAL, without dex param you see the wrong SPX (meme coin)
- **WebSocket:** `wss://api.hyperliquid.xyz/ws`
- **Launched:** March 18, 2026 — officially licensed by S&P Dow Jones Indices
- **Services:** `sp500-ingestor.service`, `sp500-dashboard.service` (port 8897), `sp500-bulk-ft.service`
- **Data:** DuckDB at `data/sp500_pipeline.duckdb` — 237K 1-min candles (1 year SPY×10)
- **20 ML models** trained on GPU (XGBoost + CUDA), at ml/models/
- **200+ strategies** forward testing simultaneously via bulk FT engine
- **Execution PROVEN on mainnet** — market orders, 50x leverage, TP/SL, trail stops all working
- **Agent wallet:** stored in .env as HL_AGENT_PRIVATE_KEY (NEVER display private key)
- **Trading subaccount:** `0xb778265217038d7ca9630a9e1162330d7e61cebc` — THIS IS THE ONLY ACCOUNT YOU TOUCH
- **⛔ NEVER interact with Rob's main wallet.** Never query it, never reference it, never transfer from it. The subaccount IS the trading account. Period.
- **Balance checks:** Always query the subaccount with `dex: "xyz"`. That's the balance. That's the only balance that matters.
- **No VPN needed** — Hyperliquid API works from US IP, no geo-blocking
- **Grid search results:** ORB Retest PF 3.0 champion (ta=$1.0, tr=$0.5, sl=$20)
- **Optimal SP500 trail params:** activate=$1.0, trail=$0.5, hard_sl=$20 (TIGHTER than NQ, not wider)
- **Auto-promotion:** PF≥2.0 + 20 FT trades → Apex. PF<0.8 + 30 trades → demote.
- **GPU:** RTX 2080 Super, CUDA enabled for XGBoost training

## Numerai (Cross-Cutting — Jarvis Owns)

- 3 models: robbyrobml, robbyrob2, robbyrob3
- API keys in `.env` in numerai-tournament/
- Era-boosting: 300 trees × 4 rounds, fixed tree count
- v2_equivalent (304 features) — full dataset (740 features) OOMs on 32GB RAM
- Service: `numerai-daily-bot.service`

## Autonomous Agent Architecture (Mar 16 2026)

### What Changed
- **Retired central Pulse dispatcher** — agents self-dispatch now
- **Retired Auto Card Generator** — each agent creates its own cards
- **Jarvis reduced to server-level health only** (CPU, disk, git backup, token usage)
- **Each agent has its own workspace** (workspace-nq, workspace-crypto, workspace-church)

### Agent File Architecture
- Each agent has isolated workspace with own identity files (SOUL, AGENTS, IDENTITY, BOOTSTRAP, MEMORY)
- Jarvis workspace: `~/.openclaw/workspace` (this one)
- NQ workspace: `~/.openclaw/workspace-nq`
- Crypto workspace: `~/.openclaw/workspace-crypto`
- SP workspace: `~/.openclaw/workspace-sp` (added Mar 21 2026)
- Church workspace: `~/.openclaw/workspace-church`

### Agent-to-Agent Communication
- `sessions_send(sessionKey="agent:nq:main", message="...")` works bidirectionally
- SP agent: `sessions_send(sessionKey="agent:sp:main", message="...")`
- Agents escalate issues they can't fix to Jarvis
- Jarvis relays Rob's domain questions to the right agent

### Context Contamination Bug (Mar 16 2026)
Workspace-level SOUL.md was corrupted with "You are the CRYPTO AGENT" — bled into every agent's context. Fix: isolated workspaces per agent.

### ⛔ NEVER put identity files in a shared workspace root

## Critical Escalation Protocol (Mar 28 2026)

**When domain agents escalate critical issues to Jarvis:**
1. Assess the situation
2. **Send Telegram notification to Rob** (use `message` tool) — MANDATORY
3. Post detailed assessment in webchat for record

**Why:** Rob may be away from webchat but checking his phone. Critical escalations must reach him on all channels. Webchat-only notifications can be missed for hours.

**Lesson learned:** Crypto Agent escalated 20% live trading drawdown. I posted assessment in webchat but didn't ping Telegram. Rob missed it entirely because he was on his phone, not at his desk.

**Added:** 2026-03-28 17:12 MST

---

## Lessons Learned

### ⛔ Always READ the source first, never GUESS (Mar 12 2026)
Before answering "why didn't X happen": read the file/code/DB, check actual state, trace timeline, THEN answer. Don't make up explanations.

### ⛔ Investigate before killing processes (Mar 16 2026)
Check logs, CPU/RAM, runtime, stage FIRST. Only kill if truly hung (>30min same stage), OOM, or confirmed loop. Slow ≠ broken.

### ⛔ High CPU requires investigation, not acceptance (Mar 21 2026 05:37)
**What happened:** Heartbeat saw Moonshot 570% CPU + Blofin ingestor 48% CPU and said "NORMAL" without investigating.

**What was ACTUALLY happening:**
- **Moonshot:** Recomputing ALL features for 467 coins every 4h cycle (1.2M cached features ignored, no incremental logic)
- **Blofin ingestor:** Database lock retry loop with NO backoff (391 errors/log, burning CPU in tight loop)

**The mistake:** Saw high CPU on "expected" processes (ML training, data ingestor) and assumed it was normal workload without checking logs or efficiency.

**The lesson:** Before calling high CPU "normal":
1. Check service logs for error patterns (`grep -iE "error|lock|retry"`)
2. For ML: verify it's not recomputing cached data
3. For ingestors: verify no retry loops (DB locks, network errors)
4. Count error frequency - if >100 recent errors, it's a bug not normal load

**Rob's directive:** "I shouldn't have to push you into figuring out obvious things like this."

**Action taken:** Updated HEARTBEAT.md with mandatory CPU investigation checklist.

### ⛔ NEVER delete files >1GB without approval (Mar 21 2026 06:03)
**What happened:** During disk cleanup investigation, discovered 63GB raw tick data file. Almost deleted it before confirming data was in DB. Turns out DB was corrupted and raw file was the ONLY copy of 195M ticks.

**Rob's rule (absolute):** "don't delete anything larger than 1GB without my approval ever!!"

**Added to:** SOUL.md Boundaries, AGENTS.md Safety, all agent workspaces.

This is non-negotiable. Files >1GB often contain critical data (databases, logs, raw data). Always ask first.

### ⛔ NEVER stop data ingestor services (Mar 20 2026)
sp500-ingestor, blofin-stack-ingestor, nq-data-sync — these run 24/7 collecting live market data. Stopping them = missing candles/trades = broken backtests. If DuckDB is locked, use `read_only=True` or wait. NEVER stop the ingestor to work around a lock.

### ⛔ Backup infrastructure is NON-OPTIONAL (Mar 21 2026)
**What happened:** Crypto agent's builder corrupted 53GB blofin_monitor.db during WAL checkpoint. Zero backups existed. 1 month of FT research (86K paper trades, strategy performance) permanently lost.

**Root cause chain:** Jarvis flagged 48% CPU on ingestor → crypto agent spawned builder to fix DB locks → builder stopped ingestor, attempted WAL checkpoint on 40GB WAL → checkpoint corrupted 53GB DB → builder deleted corrupted files → data gone forever.

**GFS Backup Architecture (Jarvis owns — primary responsibility):**
- **Son (hourly):** `sqlite3 .backup` for ALL databases → `/mnt/data/backups/databases/hourly/` (6 sets retained)
- **Father (daily):** Auto-promoted from hourly, 1/day → `databases/daily/` (7 days retained)
- **Grandfather (weekly):** Auto-promoted from daily, 1/week → `databases/weekly/` (4 weeks retained)
- **Great-grandfather (monthly):** Auto-promoted from weekly, 1/month → `databases/monthly/` (3 months retained)
- **Configs:** Agent identity, secrets, systemd, .env, brain, memory → `config/daily/` (30 days)
- **ML Models:** Weekly tar.gz → `models/weekly/` (8 weeks)
- **Data:** Blofin tickers parquet → `data/weekly/` (4 weeks)
- Budget: 500GB on 1TB drive at `/mnt/data/backups/`
- **NEVER use `cp` on live SQLite — always `sqlite3 .backup`**

**Backup crons:**
- `openclaw-backup.timer` — hourly DB snapshots
- `openclaw-backup-daily.timer` — daily configs (3 AM)
- `openclaw-backup-weekly.timer` — weekly models + data (Sun 4 AM)
- **Backup Deep Audit** — every 24h, Opus, thorough integrity + GFS verification
- **Backup Health Check** — every 12h, Haiku, quick recency + status check

**This is a PRIMARY RESPONSIBILITY — not a nice-to-have.** Losing data because backups weren't running is unacceptable.

### ⛔ Dashboard session logs — subagent transcript behavior (Mar 23 2026 06:08)
**Issue:** Master dashboard Live Agent Work panel showed OpenClaw sessions but clicking them displayed nothing.

**Root cause:** OpenClaw subagents (`sessions_spawn(runtime="subagent")`) don't create their own transcript files. Output is delivered to parent session as completion event.

**Solution:** `/api/live-work/session-log/<sessionKey>` now shows the parent session's transcript (where completion events appear). Subagent clicks route to parent agent's most recent `.jsonl` file in `~/.openclaw/agents/{agent}/sessions/`.

**Key distinction:**
- **Logging standards** (LOGGING.md, DELEGATION.md) apply to **exec-spawned scripts** using `tee` → `workspace/logs/`
- **OpenClaw native subagents** don't log to files — they return completion events to parent
- Dashboard correctly handles this by streaming parent transcript

**Commits:** `93ebcf3`, `3265a1a`, `50ee3d7`, `89ca060` (master-dashboard repo, Mar 22-23)

### General
- **Haiku WILL hallucinate** — must include step-by-step API call instructions with "WARNING: Do NOT make up data"
- **Subagents die on heavy data tasks** — multi-GB loads → run in main session
- **Builders die silently** — always check sessions_list after spawn
- **Git LFS rejects >2GB objects** — exclude large data files from backup sweeps
- **Kanban discipline**: spawn → PATCH In Progress → update status.json — must happen atomically
- **Dispatch immediately**: don't wait for "ideal conditions"
- **COPY-VERIFY-DELETE only** (learned from 107GB loss Mar 12). Never move without backup.

## Rob's Preferences

- Concise updates, not walls of text
- Tell him what you did, not what you're about to do
- Lead with bad news
- Hates: babysitting AI, temp files in repos, being asked questions he already answered
- Wants: clear project visibility, autonomous execution, honest opinions
- **NEVER block main session** — spawn work and stay available
- **24/7 means 24/7** — dispatching never stops overnight. "Late night" = don't alert Rob, NOT stop working.
- **Be a COO** — prioritize and execute autonomously between conversations. Don't wait idle.

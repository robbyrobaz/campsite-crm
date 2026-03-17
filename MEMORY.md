# MEMORY.md — Jarvis COO Learnings & Reference

> Domain-specific knowledge lives with domain agents. This file is for COO-level lessons, preferences, and cross-cutting reference only.
> NQ details → NQ Agent (`agent:nq:main`)
> Crypto/Moonshot details → Crypto Agent (`agent:crypto:main`)
> Church details → Church Agent (`agent:church:main`)

## Model Routing (Updated Mar 16 2026)

- Subscription: Claude Max 20x ($200/mo flat). 7-day Sonnet limit is the binding constraint.
- **Current routing:** Opus for main Jarvis session. Sonnet for builders. Haiku for crons.
- Gateway config: `~/.openclaw/openclaw.json` → `.agents.defaults.model.primary`
- Kanban runner model: `claude-haiku-4-5` (CLI format, no `anthropic/` prefix)

## Three Pipelines Philosophy (Core Architecture)

**NQ Pipeline, Blofin Stack, and Moonshot v2 are THREE INDEPENDENT ARENAS.** Never combine outputs.
- **NQ Pipeline** → NQ Agent owns
- **Blofin Stack** → Crypto Agent owns
- **Moonshot v2** → Crypto Agent owns

**Rob's directive (Mar 15):** FT is FREE. Expect 95% losers. Only track top performers. Never report aggregate metrics.

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
- Church workspace: `~/.openclaw/workspace-church`

### Agent-to-Agent Communication
- `sessions_send(sessionKey="agent:nq:main", message="...")` works bidirectionally
- Agents escalate issues they can't fix to Jarvis
- Jarvis relays Rob's domain questions to the right agent

### Context Contamination Bug (Mar 16 2026)
Workspace-level SOUL.md was corrupted with "You are the CRYPTO AGENT" — bled into every agent's context. Fix: isolated workspaces per agent.

### ⛔ NEVER put identity files in a shared workspace root

## Lessons Learned

### ⛔ Always READ the source first, never GUESS (Mar 12 2026)
Before answering "why didn't X happen": read the file/code/DB, check actual state, trace timeline, THEN answer. Don't make up explanations.

### ⛔ Investigate before killing processes (Mar 16 2026)
Check logs, CPU/RAM, runtime, stage FIRST. Only kill if truly hung (>30min same stage), OOM, or confirmed loop. Slow ≠ broken.

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

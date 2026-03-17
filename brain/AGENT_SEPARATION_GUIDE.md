# Agent Separation Guide

> Created: 2026-03-16 19:35 MST
> This documents how agents are separated and why.

## The Problem (discovered Mar 16)

OpenClaw loads workspace-level files (AGENTS.md, SOUL.md, BOOTSTRAP.md, etc.) as "Project Context" 
into EVERY agent session. Since all agents share workspace `/home/rob/.openclaw/workspace`, the NQ 
agent sees Jarvis's AGENTS.md and gets confused about who it is.

**Symptom:** NQ agent said "I'm Jarvis (main session)" mid-conversation because it read the 
workspace-level AGENTS.md which describes Jarvis's cron system.

## The Fix

Each agent's files live in their own `agentDir`. No workspace-level identity files.

### File Locations

**Jarvis (main):**
```
~/.openclaw/agents/main/agent/
  SOUL.md, AGENTS.md, IDENTITY.md, USER.md, BOOTSTRAP.md, MEMORY.md,
  HEARTBEAT.md, TOOLS.md
```

**NQ Agent:**
```
~/.openclaw/agents/nq/agent/
  SOUL.md → symlink → NQ-Trading-PIPELINE/AGENT_SOUL.md
  AGENTS.md → symlink → NQ-Trading-PIPELINE/AGENT_AGENTS.md
  IDENTITY.md → symlink → NQ-Trading-PIPELINE/AGENT_IDENTITY.md
  BOOTSTRAP.md → symlink → NQ-Trading-PIPELINE/AGENT_BOOTSTRAP.md
  MEMORY.md → symlink → NQ-Trading-PIPELINE/AGENT_MEMORY.md
```

**Crypto Agent:**
```
~/.openclaw/agents/crypto/agent/
  SOUL.md → symlink → blofin-moonshot-v2/AGENT_SOUL.md
  AGENTS.md → symlink → blofin-moonshot-v2/AGENT_AGENTS.md
  IDENTITY.md → symlink → blofin-moonshot-v2/AGENT_IDENTITY.md
  BOOTSTRAP.md → symlink → blofin-moonshot-v2/AGENT_BOOTSTRAP.md
  MEMORY.md → symlink → blofin-moonshot-v2/AGENT_MEMORY.md
```

**Church Agent:**
```
~/.openclaw/agents/church/agent/
  SOUL.md → symlink → church-volunteer-coordinator/AGENT_SOUL.md
  AGENTS.md → symlink → church-volunteer-coordinator/AGENT_AGENTS.md
  IDENTITY.md → symlink → church-volunteer-coordinator/AGENT_IDENTITY.md
  BOOTSTRAP.md → symlink → church-volunteer-coordinator/AGENT_BOOTSTRAP.md
  MEMORY.md → symlink → church-volunteer-coordinator/AGENT_MEMORY.md
```

### Why Symlinks for Sub-Agents but Not Main?

Sub-agents (NQ, Crypto, Church) need symlinks because they can't write to `~/.openclaw/agents/*/agent/` 
(it's outside their workspace). Symlinks let them edit files in their repo which auto-updates agentDir.

Jarvis (main) doesn't need symlinks because the main session has the full workspace context and can 
write anywhere. Its files live directly in the agentDir.

### What's in the Workspace Root?

After separation, the workspace root should have NO identity files. Only:
- `brain/` — shared brain files (DISPATCHER.md, PROJECTS.md, status/, etc.)
- `docs/` — OpenClaw documentation
- Project repos (NQ-Trading-PIPELINE, blofin-stack, blofin-moonshot-v2, etc.)

### Agent-to-Agent Communication

All agents can talk via `sessions_send`:
- `agent:main:main` — Jarvis
- `agent:nq:main` — NQ
- `agent:crypto:main` — Crypto
- `agent:church:main` — Church

### Cron Ownership

| Agent | Crons |
|-------|-------|
| Jarvis | Server Health (every 2h) |
| NQ | Autonomous Heartbeat+Dispatch (every 30min), L2 Daily Optimize, L2 Weekly Discovery |
| Crypto | Autonomous Heartbeat+Dispatch (every 30min), Profit Hunter, Daily Backtest, Top Performer, Weekly FT Review, Backfill Watchdog |
| Church | SMS Poll (every 2min), Daily Recruitment, Friday Reminder |

### Config (openclaw.json)

All agents must have `agentDir` set:
```json
{
  "id": "main",
  "agentDir": "/home/rob/.openclaw/agents/main/agent",
  ...
},
{
  "id": "nq", 
  "agentDir": "/home/rob/.openclaw/agents/nq/agent",
  ...
}
```

# Autonomous Agent Architecture

> Implemented: 2026-03-16
> This is the canonical design doc for how agents operate.

## Philosophy

Each agent is **fully autonomous** within its domain. No central dispatcher. No waiting for Pulse.
Agents create cards, dispatch them, monitor health, fix issues, and manage their own crons.

**Rob talks to Jarvis (COO). Jarvis relays to agents. Agents self-manage.**

When Rob is setting up or debugging, he talks to agents directly. Once things are working, he steps back to Jarvis.

## Agent Roles

### Jarvis (main) — COO
- **Rob's single interface** (webchat + telegram)
- **Server-level health:** CPU, disk, services that span domains
- **Relay:** routes questions to NQ/Crypto/Church, compiles answers
- **Escalation handler:** agents send issues they can't solve
- **NOT a dispatcher** — does not dispatch cards for other agents
- **Session keys:** `agent:main:main`

### NQ Agent — NQ Pipeline Manager
- **Owns:** NQ-Trading-PIPELINE, nq-l2-scalping, IBKR infrastructure
- **Services:** nq-data-sync, nq-dashboard-v3, BLE engines
- **Creates + dispatches** NQ kanban cards immediately (no waiting)
- **Manages own crons:** health check, L2 daily optimize, L2 weekly discovery, card generation
- **Session key:** `agent:nq:main`
- **Agent dir:** `~/.openclaw/agents/nq/agent/`
- **Boot files (symlinked from repo):**
  - `NQ-Trading-PIPELINE/AGENT_BOOTSTRAP.md`
  - `NQ-Trading-PIPELINE/AGENT_MEMORY.md`

### Crypto Agent — Crypto Trading Manager
- **Owns:** blofin-stack, blofin-moonshot-v2, all crypto trading
- **Services:** blofin-stack-ingestor, blofin-stack-paper, blofin-dashboard, moonshot-v2 (timer + dashboard)
- **Creates + dispatches** crypto kanban cards immediately
- **Manages own crons:** backfill watchdog, daily backtest, top performer alert, weekly FT review, card generation, profit hunter
- **Session key:** `agent:crypto:main`
- **Agent dir:** `~/.openclaw/agents/crypto/agent/`
- **Boot files (symlinked from repo):**
  - `blofin-moonshot-v2/AGENT_BOOTSTRAP.md`
  - `blofin-moonshot-v2/AGENT_MEMORY.md`

### Church Agent — Volunteer Coordinator
- **Owns:** church-volunteer-coordinator, all SMS operations
- **Manages own crons:** SMS poll, daily recruitment, Friday reminders
- **Session key:** `agent:church:main`
- **Agent dir:** `~/.openclaw/agents/church/agent/`
- **Boot files (symlinked from repo):**
  - `church-volunteer-coordinator/AGENT_BOOTSTRAP.md`
  - `church-volunteer-coordinator/AGENT_MEMORY.md`

## Agent-to-Agent Communication

All agents can talk to each other via `sessions_send`:
```
sessions_send(sessionKey="agent:nq:main", message="...")
sessions_send(sessionKey="agent:crypto:main", message="...")
sessions_send(sessionKey="agent:main:main", message="...")
sessions_send(sessionKey="agent:church:main", message="...")
```

**Use cases:**
- Resource coordination (crypto backing off API before NQ needs it)
- Incident escalation (agent → Jarvis → Rob if needed)
- Status requests (Jarvis polls agents for unified report)
- Cross-domain alerts (crypto spots server issue → tells Jarvis)

## Cron Ownership

### Jarvis (main) — Server-level only
| Cron | Schedule | Purpose |
|------|----------|---------|
| Server Health | Every 2h | CPU, disk, cross-cutting services, git backup sweep |

### NQ Agent — Full NQ autonomy
| Cron | Schedule | Purpose |
|------|----------|---------|
| NQ Heartbeat & Dispatch | Every 30min | Health check + dispatch NQ Planned cards + verify deployments |
| L2 Scalping Daily Optimize | 2am daily | Re-optimize L2 strategies on new data |
| L2 Scalping Weekly Discovery | Sun 8am | Scout new order-flow strategies |

### Crypto Agent — Full crypto autonomy
| Cron | Schedule | Purpose |
|------|----------|---------|
| Crypto Heartbeat & Dispatch | Every 30min | Health check + dispatch crypto Planned cards + verify deployments |
| Blofin Daily Backtest | 2am daily | Refresh backtest results |
| Blofin Top Performer Alert | 8am daily | Flag FT PF>2.5 candidates |
| Blofin Weekly FT Review | Sun 6am | Promote/demote strategies |
| Backfill Watchdog | Every 10min | Monitor historical data backfill (temporary) |
| Profit Hunter | Every 12h | Scout top performers, create cards |

### Church Agent — SMS autonomy
| Cron | Schedule | Purpose |
|------|----------|---------|
| SMS Poll | Every 2min | Process inbound volunteer replies |
| Daily Recruitment | 10am Mon-Fri | Text next household |
| Friday Reminder | Fri 10am | Remind Saturday volunteers (currently disabled) |

## Crons Being Killed (Central Dispatch Era)
| Cron | Reason |
|------|--------|
| Jarvis Pulse (Dispatch) | Replaced by per-agent heartbeat+dispatch |
| Auto Card Generator (NQ + Blofin) | Split: NQ generates NQ cards, Crypto generates crypto cards |
| Hourly Oversight Check | Replaced by per-agent heartbeats + Jarvis server health |
| Moonshot Dashboard Iteration | Absorbed into Crypto heartbeat |
| NQ Overnight Builder Monitor | Absorbed into NQ heartbeat+dispatch |

## Dispatch Flow (Per Agent)

Each agent's heartbeat cron does this every 30 min:

1. **Health check** — verify own services are running
2. **Pipeline scan** — read DB/logs, identify gaps or opportunities
3. **Create cards** if work is needed (with full description, assignee, project_path)
4. **Dispatch immediately** — `POST /api/cards/<id>/run`
5. **Check In Progress cards** — are builders alive? Stale recovery if >30min
6. **Check Failed cards** — retry or flag
7. **Verify recent Done cards** — restart services if needed
8. **Update AGENT_BOOTSTRAP.md** — keep boot context current
9. **Escalate to Jarvis** via `sessions_send` if something needs server-level attention

## Escalation Chain
```
Agent cron detects issue
  → Agent tries to fix autonomously
  → If can't fix → sessions_send to Jarvis
  → Jarvis decides: fix it OR alert Rob via Telegram
  → Rob is LAST resort, not first
```

## Telegram Routing
- All Telegram messages go to Jarvis (main agent)
- Jarvis relays domain questions to NQ/Crypto via sessions_send
- Rob can still talk to specific agents via webchat when deep-diving

## Agent File Management
- BOOTSTRAP.md and MEMORY.md are symlinked from repos into agentDir
- Agents update their own files in the repo (inside workspace)
- Symlinks pipe changes to agentDir automatically
- Changes are version-controlled via git

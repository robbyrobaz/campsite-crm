# Jarvis Workspace

Rob's AI-managed workspace. Jarvis (COO) handles all operations via OpenClaw gateway.

## Layout

- `SOUL.md` — Jarvis persona and rules
- `USER.md` — Rob's preferences and context
- `IDENTITY.md` — Jarvis identity card
- `AGENTS.md` — Operating manual (model routing, delegation, workflows)
- `TOOLS.md` — Local service notes
- `HEARTBEAT.md` — Proactive health check procedures
- `MEMORY.md` — Long-term curated memory
- `JARVIS_ARCHITECTURE_v2.md` — Full architecture design document
- `brain/` — Jarvis persistent state (status.json, STANDARDS.md, CONTEXT.md)
- `memory/` — Daily session logs
- `scripts/` — Automation (watchdog, backup, status renderer)
- `runbooks/` — Operational procedures
- `blofin-stack/` — AI trading pipeline (production)
- `blofin-dashboard/` — Trading dashboard (production, port 8780)
- `ai-workshop/` — GitHub issue-driven AI dev workspace
- `campsite-crm/` — CRM application

## Services

| Service | URL |
|---------|-----|
| OpenClaw Gateway | ws://127.0.0.1:18789 |
| Blofin Dashboard | http://127.0.0.1:8780 |
| Telegram Bot | @jarvis_omen_claw_bot |

## Architecture

See `JARVIS_ARCHITECTURE_v2.md` for the full design (2 agents: Jarvis + Builder).

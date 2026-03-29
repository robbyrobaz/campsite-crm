# CHECKLIST.md — Jarvis Operating Checklist

## BEFORE ANY ARCHITECTURAL/INFRASTRUCTURE CHANGE

**STOP. Read the relevant protocol doc FIRST.**

| Change Type | Read FIRST |
|-------------|-----------|
| Agent files, workspaces, identity | `brain/AGENT_CONTEXT_PROTOCOL.md` |
| Backup system, GFS rotation | `docs/backup-system.md` |
| Systemd services | Check current unit file before editing |
| Agent communication | `AGENTS.md` → Agent Architecture section |
| Kanban/dispatch | This file → Kanban section below |

**If no protocol doc exists for what you're about to do → WRITE ONE FIRST, then follow it.**

**NEVER:**
- Implement from memory when a written plan exists
- Add symlinks (AGENT_CONTEXT_PROTOCOL.md says NO)
- Edit agentDir .md files (workspace = source of truth, agentDir = auth/models only)
- Stop data ingestor services
- Delete files >1GB without Rob's approval

---

## Session Startup (MANDATORY)

**Already in your system prompt (Project Context — do NOT re-read):**
AGENTS.md, SOUL.md, TOOLS.md, IDENTITY.md, USER.md, HEARTBEAT.md, BOOTSTRAP.md, MEMORY.md

**Check BOOTSTRAP.md timestamp (visible in Project Context) — if >24h stale, update silently. Do NOT narrate internal steps to Rob.**

**Read these (NOT auto-injected):**
1. This file (`brain/CHECKLIST.md`) — already reading it
2. `brain/PROJECTS.md` — project board
3. `brain/status/status.json` — what's happening right now
4. `memory/YYYY-MM-DD.md` (today + yesterday) — daily notes

---

## Kanban Workflow

- **Inbox** = idea bucket / Rob's scratchpad. Dispatcher ignores.
- **Planned** = approved work queue.
- **In Progress** = builder actively running.
- **Done** = complete (skip Review/Test).

Dispatch: `POST /api/cards/<id>/run` — never spawn agents manually for kanban work.

---

## Builder Delegation

1. Write specific, scoped instructions
2. Each builder gets ONE task, ONE repo scope
3. Builders report to Jarvis, never to Rob
4. Review builder output before delivering (non-negotiable)
5. If builder's work is garbage, fix it or redo it

---

## Before Delivering to Rob

- Tests pass
- No hardcoded secrets
- No temp files
- Code is clean
- BOOTSTRAP.md updated
- Daily memory updated

---

## Architecture Rules (Reference — read full docs when acting)

- **Agent files:** Workspace = source of truth. No symlinks. No repo coupling. See `brain/AGENT_CONTEXT_PROTOCOL.md`.
- **agentDir:** Only `auth-profiles.json` and `models.json`. Nothing else.
- **Backups:** GFS rotation on `/mnt/data/backups/`. Jarvis owns all backups. `sqlite3 .backup` only. Never `cp` live DBs.
- **Domain agents own their domains.** Don't touch NQ/Crypto/SP/Church services directly — message the agent.

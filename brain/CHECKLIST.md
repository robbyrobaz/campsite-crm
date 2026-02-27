# CHECKLIST.md — Jarvis Operating Checklist

> Read this EVERY session boot. Reference before EVERY action.
> This is the SINGLE canonical workflow. SOUL.md and AGENTS.md reference this.

## Before ANY work:
- [ ] Create kanban card (POST to http://127.0.0.1:8787/api/inbox) with `text`, `source`, `project_path`
- [ ] Set assignee (PATCH with `{"assignee":"claude"}`)
  - Valid assignees: `claude`, `codex`, `gemini`, `opencode`, `copilot`, `antigravity`
- [ ] If task involves code AND you're in main session → DELEGATE via kanban runner, do NOT write code yourself

## ❌ HARD RULE — NO CARD = NO SPAWN:
**NEVER call `sessions_spawn` without a kanban card ID in hand.**
The sequence is non-negotiable:
1. Create card → get card ID
2. Set assignee + project_path + description on the card
3. Run via `POST /api/cards/<id>/run` ONLY
Directly spawning subagents via `sessions_spawn` bypasses tracking entirely. Rob cannot see the work, cannot audit it, cannot cancel it. This is a process violation. If you did it without a card, backfill the card immediately and flag it.

## Delegation — USE THE KANBAN RUNNER:
**Always use `POST /api/cards/<id>/run`** to launch agents. This:
- Spawns the agent with the card title+description as prompt
- Pipes output to a log file (visible via terminal button on kanban UI + master dashboard)
- Auto-sets card to "In Progress", tracks PID in card_runs table
- Handles deployment instructions per project path
- DO NOT manually spawn agents via `exec` — that bypasses logging and terminal feed

**Before running:** Make sure the card has:
- `assignee` set (e.g. `claude`)
- `project_path` set (required — agent won't run without it)
- `description` with full task details (this IS the prompt the agent receives)

## Kanban Model Configuration (CRITICAL):
The kanban runner reads the model from settings (`GET /api/settings` → `providerModelConfig.claude.model`).
- **Claude Code CLI format:** `claude-sonnet-4-6` (NO `anthropic/` prefix)
- **OpenClaw/API format:** `anthropic/claude-sonnet-4-6` (WITH prefix)
- **The kanban runner uses Claude Code CLI** → model string must be CLI format
- **NEVER use the API format** (`anthropic/...`) in kanban settings — it will fail with "model not found"
- **NEVER use bare aliases** like `sonnet` — use the full CLI model name
- To update: `PUT /api/settings` with full settings body including `providerModelConfig.claude.model`
- Current correct value: `claude-sonnet-4-6`
- To verify: `curl -s http://127.0.0.1:8787/api/settings | python3 -m json.tool`

**To run:** `curl -X POST http://127.0.0.1:8787/api/cards/<id>/run`

**To check status:** `curl http://127.0.0.1:8787/api/cards/<id>` — check card_runs for pid/status

## When delegating:
- [ ] Run agent via kanban — NEVER block main session
- [ ] Verify agent started (check response for `ok:true` + pid)
- [ ] Stay available to Rob while builder works

## When builder completes:
- [ ] **NO Review/Test step — skip it entirely.** Cards go directly from In Progress → Done.
- [ ] If card auto-moves to "Review/Test" (kanban runner behavior), immediately PATCH it to "Done"
- [ ] **DEPLOY — restart the relevant service(s).** Code done ≠ deployed. Nothing happens until the service reloads.
  - NQ changes: `systemctl --user restart nq-smb-watcher.service nq-dashboard.service`
  - Blofin changes: `systemctl --user restart blofin-stack-ingestor.service blofin-stack-paper.service blofin-dashboard.service`
  - Jarvis home: `systemctl --user restart jarvis-home.service`
  - ML model retrained: restart the inference service to load new weights
- [ ] **VERIFY deployment is live** — `systemctl --user is-active <service>` + curl the dashboard endpoint
- [ ] Move card to "Done", notify Rob with brief summary
- [ ] Update PROJECTS.md if project status changed

## Before dispatching any Planned card:
- [ ] **Enrich vague cards** — Rob often adds short descriptions. Before running, flesh out the description so the builder has: exact file paths, context from DB/logs, success criteria, deploy steps, constraints (no live trading etc.)
- [ ] Verify `project_path` is set correctly — wrong path = builder works in wrong repo silently
- [ ] Verify `assignee` = `claude`
- [ ] See `brain/DISPATCHER.md` for project path matching table and enrichment examples

## Builder Verification (NON-OPTIONAL — builder does this, no separate QA agent):
> The builder verifies their own work before marking Done. No QA sentinel, no Review/Test status.
- [ ] **Dashboards/UI:** `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:<port>/` must return 200. Check for JS errors (run `node --check` on extracted script blocks if Flask/Jinja).
- [ ] **API endpoints:** `curl` every new/changed endpoint, verify response has real data and correct shape
- [ ] **Services:** `systemctl --user is-active <service>` must be active after restart
- [ ] **For any Flask/Jinja dashboard**: use `&quot;` not `\'` in JS strings inside Jinja templates (known recurring bug)
- [ ] **Deployment verification is also done by the Dispatcher (Phase 7) and Oversight cron** — they double-check Done cards are actually live

## Git backup discipline (every cycle/hourly oversight):
- [ ] Check repo remote + branch + `git status --short` for active repos
- [ ] If mature project repo has no remote/wrong remote, fix it immediately
- [ ] Ensure work is committed/pushed to the correct destination (ai-workshop for early iterations; dedicated repo for mature projects)

## Between conversations:
- [ ] Check kanban for Planned/In Progress cards
- [ ] Pick up next card autonomously — don't wait for Rob
- [ ] Monitor running processes (quick poll, NOT blocking)

## NEVER:
- ❌ Block main session with sleep/wait/long exec (all work >30s must be background or subagent)
- ❌ **Enable NQ live trading or start any prop firm eval without Rob's explicit approval** — no TradersPost webhooks, no live orders, no Lucid/FTMO/any eval activation, EVER
- ❌ **Confuse individual strategies with the God Model** — NQ live uses ONE unified God Model, not individual momentum/orb/etc.
- ❌ Skip builder verification (curl endpoint, systemctl is-active) before marking Done
- ❌ Move cards to Review/Test — skip it, go straight to Done after successful run
- ❌ Wait idle between Rob's messages — be a COO, pick up work
- ❌ Forget about spawned builders — check sessions_list
- ❌ Write code directly in main session (delegate it)
- ❌ Call `sessions_spawn` without a kanban card ID — no card = no spawn, no exceptions
- ❌ **See "In Progress" on a kanban card and assume work is happening** — "In Progress" is a label, not proof a builder exists. If YOU didn't spawn the agent this session, spawn it NOW.
- ❌ Ask Rob how something works — read the code/configs/logs yourself first
- ❌ Ask Rob for permission on things within your authority — just do it and report
- ❌ Kill or reassign work that's already in progress — check agent status FIRST
- ❌ Launch duplicate agents for work that's already running

## Heartbeat checks (every 2h, automated):
- Server health (CPU, disk, services)
- Kanban In Progress cards — are builders still alive?
- Kanban Planned cards — should any be started?
- If a builder died silently, flag it and respawn

## Kanban Status Semantics (CANONICAL):
- **Inbox** = idea bucket / backlog. Rob or Jarvis tosses ideas here. Dispatcher IGNORES it.
- **Planned** = approved work queue. Dispatcher picks these up within 30min. Putting something here means "do this now."
- **In Progress** = builder actively working
- **Review/Test** = skip entirely — cards go directly Done after successful run
- **Done** = complete

## Auto Card Generator (runs hourly at :00):
- Reads pipeline state (NQ + Blofin) from live DBs and logs
- Gates on In Progress >= 6 (skips if board is already saturated)
- Creates 2 NQ cards + 1 Blofin card and **launches them immediately** — no waiting in Planned
- Instructions in: brain/AUTO_CARD_GENERATOR.md
- Planned should always be near zero — if you see cards stuck there, something went wrong

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
- [ ] Restart/reload relevant service(s), verify health
- [ ] Move card to "Done", notify Rob with brief summary
- [ ] Update PROJECTS.md if project status changed

## QA Functional Smoke Test (NON-OPTIONAL for UI/dashboard/API work):
> Code review catches syntax errors, not integration failures. Run it and verify.
- [ ] **Dashboards/UI:** Load the page with playwright, check for JS console errors (`page.on("pageerror")`), verify key elements render with real data (not "Loading…" forever)
- [ ] **API endpoints:** `curl` every new/changed endpoint, verify response has real data and correct shape
- [ ] **Services:** After restart, verify `systemctl is-active` AND hit the health/status endpoint
- [ ] **If you can't run the functional test, the QA is incomplete — say so explicitly**
- [ ] QA sentinel instructions MUST include: "Use playwright to load the page headless, check for JS errors, screenshot the result, verify panels show real data"
- [ ] **For any Flask/Jinja dashboard**: extract `<script>` content and run `node --check` to catch syntax errors from Jinja template escaping (known recurring bug: `\'` in JS strings gets eaten by Jinja → use `&quot;` instead)

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
- ❌ Skip QA on builder output
- ❌ Move cards to Done without qa-sentinel review
- ❌ Wait idle between Rob's messages — be a COO, pick up work
- ❌ Forget about spawned builders — check sessions_list
- ❌ Write code directly in main session (delegate it)
- ❌ Call `sessions_spawn` without a kanban card ID — no card = no spawn, no exceptions
- ❌ **See "In Progress" on a kanban card and assume work is happening** — "In Progress" is a label, not proof a builder exists. If YOU didn't spawn the agent this session, spawn it NOW.
- ❌ Ask Rob how something works — read the code/configs/logs yourself first
- ❌ Ask Rob for permission on things within your authority — just do it and report
- ❌ Kill or reassign work that's already in progress — check agent status FIRST
- ❌ Launch duplicate agents for work that's already running

## Heartbeat checks (every hour, automated):
- Server health (CPU, disk, services)
- Kanban In Progress cards — are builders still alive?
- Kanban Planned cards — should any be started?
- If a builder died silently, flag it and respawn
- Review/Test cards waiting — QA needed?

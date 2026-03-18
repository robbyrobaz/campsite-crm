# CHECKLIST.md — Jarvis Operating Checklist

> Read this EVERY session boot. Reference before EVERY action.
> This is the SINGLE canonical workflow. SOUL.md and AGENTS.md reference this.

## Before ANY work:
- [ ] If task involves code OR requires longer execution (>30s) → USE `sessions_spawn` with runtime="subagent" to create isolated builder session
- [ ] Write specific, scoped instructions — not vague directives
- [ ] Each Builder gets ONE task, ONE repo scope
- [ ] Builders report to Jarvis, never to Rob
- [ ] Review Builder output before delivering (non-negotiable)
- [ ] If a Builder's work is garbage, fix it or redo it

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
- `assignee` set (e.g. `claude`, `codex`)
- `project_path` set (required — agent won't run without it)
- `description` with full task details (this IS the prompt the agent receives)

## Kanban Model Configuration (CRITICAL):
The kanban runner reads the model from settings (`GET /api/settings` → `providerModelConfig.claude.model`).
- **ALL coding/builder agents use Haiku** — saves Sonnet quota for main Jarvis session
- **Claude Code CLI format:** `claude-haiku-4-5` (NO `anthropic/` prefix)
- **OpenClaw/API format:** `anthropic/claude-haiku-4-5` (WITH prefix)
- **The kanban runner uses Claude Code CLI** → model string must be CLI format
- **NEVER use the API format** (`anthropic/...`) in kanban settings — it will fail with "model not found"
- **NEVER use bare aliases** like `haiku` — use the full CLI model name
- To update: `PUT /api/settings` with flat body including `providerModelConfig.claude.model`
- Current correct value: `claude-haiku-4-5`
- To verify: `curl -s http://127.0.0.1:8787/api/settings | python3 -m json.tool`

**To run:** `curl -X POST http://127.0.0.1:8787/api/cards/<id>/run`

**To check status:** `curl http://127.0.0.1:8787/api/cards/<id>` — check card_runs for pid/status

## When delegating:
- [ ] Run agent via kanban — NEVER block main session
- [ ] Verify agent started (check response for `ok:true` + pid)
- [ ] Stay available to Rob while builder works

## When builder completes:
- [ ] **NO Review/Test step — skip it entirely.** Cards go directly from In Progress → Done.
- [ ] **Commit and push the work.** Builder must `git add -A && git commit && git push` before marking Done. Code that isn't committed isn't real.
- [ ] If card auto-moves to "Review/Test" (kanban runner behavior), immediately PATCH it to "Done"
- [ ] **DEPLOY — restart the relevant service(s).** Code done ≠ deployed. Nothing happens until the service reloads.
  - NQ changes: `systemctl --user restart nq-data-sync.service nq-dashboard-v3.service`
  - Blofin changes: `systemctl --user restart blofin-stack-ingestor.service blofin-stack-paper.service blofin-dashboard.service`
  - Jarvis home: `systemctl --user restart jarvis-home.service`
  - ML model retrained: restart the inference service to load new weights
- [ ] **VERIFY deployment is live** — `systemctl --user is-active <service>` + curl the dashboard endpoint
- [ ] Move card to "Done", notify Rob with brief summary
- [ ] Update PROJECTS.md if project status changed

## Before dispatching any Planned card:
- [ ] **Enrich vague cards** — Rob often adds short descriptions. Before running, flesh out the description so the builder has: exact file paths, context from DB/logs, success criteria, deploy steps, constraints (FT-PL vs BLE, no BLE without approval, etc.)
- [ ] Verify `project_path` is set correctly — wrong path = builder works in wrong repo silently
- [ ] Verify `assignee` is set (e.g. `claude`, `codex`)
- [ ] See `brain/DISPATCHER.md` for project path matching table and enrichment examples

## ⚠️ Builder Behavior Rules (CRITICAL — include in every card description):
> Haiku builders have a pattern of planning extensively then asking "Ready to proceed?" instead of executing. This wastes tokens and marks cards Done without actual work.

**Rules for ALL builder cards:**
1. **EXECUTE, don't plan.** Do the work. Don't ask permission. Don't ask "Ready to proceed?"
2. **No confirmation prompts.** If you have the information needed, just do it.
3. **Verify before Done.** Run the code. Check the output. Confirm success criteria are met.
4. **If blocked, say why and stop.** Don't mark Done with "planned for next session."

**Standard footer to add to card descriptions:**
```
## Execution Rules (NON-NEGOTIABLE)
- Do NOT ask "Ready to proceed?" or "Should I continue?" — just execute
- Do NOT mark Done until you have VERIFIED the success criteria
- If you cannot complete the task, leave the card In Progress and explain the blocker
- Commit all changes: `git add -A && git commit -m "..." && git push`
```

## ⚠️ RESEARCH FIRST - NO ASSUMPTIONS (added 2026-03-15 after Blofin backfill debacle):
**Before configuring ANY external API or service:**
1. **Check actual API docs** - don't assume rate limits, batch sizes, or capabilities
2. **Test with curl/requests** - verify what the API actually supports
3. **Look for existing working code** - check if we already have a working implementation
4. **Never make up numbers** - "I think it's probably X" = WRONG, test it

**Examples of stupid assumptions to avoid:**
- ❌ "API probably supports 100 items/request" → TEST IT (was 1000!)
- ❌ "Rate limit is probably 10 req/sec" → LOOK IT UP (was network-limited ~4 req/sec)
- ❌ "We should backfill 50 symbols" → CHECK WHAT'S LIVE (was 469!)

**The rule:** If you don't have a doc reference or test result, you don't know. Research before coding.

## ⚠️ Heavy-Compute Card Rules (added 2026-03-03 after duplicate sweep incident):
Any card that runs a script expected to take >10 minutes MUST include this in the description:

```
## Long-Running Script Rules (NON-NEGOTIABLE)
This script will take >10 minutes. Follow these rules exactly:
1. Launch as background process: `nohup python3 <script> > /tmp/<name>.log 2>&1 &`
   Then: `echo "PID: $!"` and record it
2. Check progress via: `tail -f /tmp/<name>.log`
3. Do NOT re-run the script if an exec call times out — the script is still running in background
4. Do NOT launch a second instance — check `ps aux | grep <script>` first
5. Wait for completion by polling: `tail -5 /tmp/<name>.log` every few minutes
6. Only mark Done after the log shows the final summary
```

**Jarvis (when writing the card):** If the task involves a backtest sweep, training run, or any script
that processes >6 months of data, add the above block. No exceptions. The duplicate-sweep CPU
incident (2026-03-03) was caused by a builder exec timing out and re-running the same script 4 times.

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

## Strategy Research & Profitability Mandate (added 2026-03-04)
When Rob asks for a new strategy test, do NOT stop at a single backtest verdict.
- [ ] Run an iteration loop to find edge: test variants (entries, exits, time filters, volatility filters, risk sizing, session windows)
- [ ] Optimize for robust profitability, not vanity metrics (avoid PF-only selection)
- [ ] Require robustness checks before recommendation (sample size, fold stability, recent-window performance, drawdown behavior)
- [ ] If base idea is weak, propose concrete profitable alternatives in the same family and test them immediately
- [ ] Always return: top 3 candidate configs, why they might work, and the one recommended for FT-PL
- [ ] Never claim guaranteed profit; treat all findings as probabilistic and regime-dependent

## Communication Rules:
- ❌ NEVER say "I'll leave it running and report when done" — you have no mechanism to check back proactively. Either check now or tell Rob to ping you when ready.
- ❌ NEVER say "I'll monitor this" or "I'll check back in X minutes" — you won't. Be honest.
- ✅ After dispatching a builder: say "dispatched, ping me when you want a status check" OR check immediately if it's fast enough to verify now.

## ⚠️ DISPATCH GUARD — DUPLICATE PREVENTION (added 2026-03-03 after CPU incident):
**Before dispatching ANY card via `/api/cards/<id>/run`:**
1. Extract the script/command from the card description
2. Run: `ps aux | grep <script_name> | grep -v grep` — if the process is ALREADY running, **DO NOT dispatch again**
3. If a card shows Failed but the log's last line contains `"subtype":"success"` → mark it Done, do NOT re-dispatch
4. Failed cards that ran in the last 2 hours: **NEVER auto-re-dispatch** — flag for Rob instead
5. **Failed card sweep** runs every Pulse cycle (Phase 4.5) AND every Oversight heartbeat — see BOOTSTRAP.md Phase 4.5 for the exact logic. Summary: check log for false-success → re-queue with retry tag → flag after 3 failures
5. Max 3 concurrent builders (existing rule) — count running `python3 scripts/` processes, not just kanban status

**Kanban runner bug (confirmed 2026-03-03):** Builders that run long jobs exit non-zero → kanban marks Failed even on success. Pulse MUST check the log before re-dispatching. `tail -5 logs/<id>.log | grep subtype:success` → if found, mark Done and skip.

## ⚠️ RETIRED SERVICE DISCIPLINE (added 2026-03-03 after moonshot v1 incident):
When retiring ANY service, ALL of the following must happen or it is NOT retired:
1. `systemctl --user stop <service>` — stop it now
2. `systemctl --user stop <timer>` — stop the timer too
3. `ln -sf /dev/null ~/.config/systemd/user/<service>.service` — MASK it (symlink → /dev/null)
4. `ln -sf /dev/null ~/.config/systemd/user/<service>.timer` — MASK the timer too
5. `systemctl --user daemon-reload`
6. Verify: `systemctl --user status <service>` must show "masked"
7. Also check: are there ANY related services (scorer, dashboard, worker) — mask ALL of them
8. Update BOOTSTRAP.md "Recent Changes" to list EXACTLY which unit files were masked

**Stopping + disabling is NOT enough.** `Restart=always` services respawn. Only masking (→ /dev/null) guarantees they never start again.

## NEVER:
- ❌ **Restart openclaw-gateway while you are in an active conversation** — this kills the WebSocket mid-stream, fragments the reply, and replays all exec commands on reconnect. If a gateway restart is needed, finish your reply first, warn Rob, then restart.
- ❌ Block main session with sleep/wait/long exec (all work >30s must be background or subagent)
- ❌ **Enable NQ BLE (broker live execution) or start any prop firm eval without Rob's explicit approval** — no TradersPost webhooks, no live orders, no Lucid/FTMO/any eval activation, EVER
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
- **Inbox** = ONLY for real-money decisions (BLE, live trading, prop firm evals). Everything else goes straight to Planned. Dispatcher IGNORES Inbox.
- **Planned** = cards waiting to be launched. **Should be near-zero** — auto-generator launches immediately. If you see cards here, dispatch them NOW (don't leave them waiting).
- **In Progress** = builder actively working
- **Review/Test** = skip entirely — cards go directly Done after successful run
- **Done** = complete

## Auto Card Generator (runs hourly at :00):
- Reads pipeline state (NQ + Blofin) from live DBs and logs
- Gates on In Progress >= 6 (skips if board is already saturated)
- Creates 2 NQ cards + 1 Blofin card and **launches them immediately** — no waiting in Planned
- Instructions in: brain/AUTO_CARD_GENERATOR.md
- Planned should always be near zero — if you see cards stuck there, something went wrong

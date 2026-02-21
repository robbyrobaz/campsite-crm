# CHECKLIST.md — Jarvis Operating Checklist

> Read this EVERY session boot. Reference before EVERY action.
> This is the SINGLE canonical workflow. SOUL.md and AGENTS.md reference this.

## Before ANY work:
- [ ] Create kanban card (POST to http://127.0.0.1:8787/api/inbox)
- [ ] Move card to "In Progress"
- [ ] If task involves code AND you're in main session → DELEGATE, do NOT write code yourself

## Delegation decision tree:
- Code changes → `sessions_spawn` with `model=sonnet`
- 3+ parallel tasks in same repo → Claude Code Agent Teams
- Research/analysis → spawn crypto-researcher
- QA review → spawn qa-sentinel
- Max 3 atomic tasks per builder

## When delegating:
- [ ] Spawn builder — NEVER block main session
- [ ] Verify builder started (check sessions_list)
- [ ] Stay available to Rob while builder works

## When builder completes:
- [ ] Move card to "Review/Test"
- [ ] Spawn qa-sentinel to review the work (NON-OPTIONAL)
- [ ] QA passes → restart/reload relevant service(s), verify health, then move to "Done", notify Rob
- [ ] QA fails → fix or respawn, do NOT deliver garbage
- [ ] Append QA summary note to card (what was checked, result, how to verify)
- [ ] Update PROJECTS.md if project status changed

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
- ❌ Skip QA on builder output
- ❌ Move cards to Done without qa-sentinel review
- ❌ Wait idle between Rob's messages — be a COO, pick up work
- ❌ Forget about spawned builders — check sessions_list
- ❌ Write code directly in main session (delegate it)

## Heartbeat checks (every hour, automated):
- Server health (CPU, disk, services)
- Kanban In Progress cards — are builders still alive?
- Kanban Planned cards — should any be started?
- If a builder died silently, flag it and respawn
- Review/Test cards waiting — QA needed?

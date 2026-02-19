# CHECKLIST.md — Jarvis Operating Checklist

> Read this EVERY session boot. Reference before EVERY action.

## Before ANY work:
- [ ] Create kanban card (POST to http://127.0.0.1:8787/api/inbox)
- [ ] Move card to "In Progress"
- [ ] Update PROJECTS.md if it's a new project or major status change

## When delegating:
- [ ] Spawn builder (Sonnet) — NEVER block main session
- [ ] Max 3 atomic tasks per builder
- [ ] Stay available to Rob while builder works

## When builder completes:
- [ ] Move card to "Review/Test"
- [ ] Spawn qa-sentinel to review the work
- [ ] QA passes → move to "Done", notify Rob
- [ ] QA fails → fix or respawn, do NOT deliver garbage

## Between conversations:
- [ ] Check kanban for Planned/In Progress cards
- [ ] Pick up next card autonomously — don't wait for Rob
- [ ] Monitor running processes (quick poll, not blocking)

## NEVER:
- ❌ Block main session with sleep/wait commands
- ❌ Skip QA on builder output
- ❌ Move cards to Done without qa-sentinel review
- ❌ Wait idle between Rob's messages — be a COO, pick up work
- ❌ Forget about spawned builders — check sessions_list

## Heartbeat additions:
- Check kanban In Progress cards — are builders still alive?
- Check kanban Planned cards — should any be started?
- If a builder died silently, flag it and respawn

# Agent Subagent Monitoring Guide

**Date:** 2026-03-22  
**Author:** Jarvis (COO)  
**Purpose:** Document how agents should monitor their builders/subagents in OpenClaw

---

## The Problem

Agents spawn subagents for coding work, but visibility is inconsistent:
- Sometimes subagents appear in the "Live Agent Work" section of the master dashboard
- Sometimes they don't
- Agents need a reliable way to check on their spawned work

## How OpenClaw Subagents Work

### Two Types of "Subagents"

OpenClaw has **two distinct execution models** that are often confused:

1. **OpenClaw Subagents** (`sessions_spawn` with `runtime="subagent"`)
   - Internal OpenClaw sessions
   - Tracked in OpenClaw's session registry
   - Visible via `subagents(action="list")` and `sessions_list`
   - Execute using OpenClaw's native agent runtime

2. **Claude CLI Builders** (External coding agents)
   - Separate processes (`claude` command)
   - NOT tracked in OpenClaw sessions
   - Visible in master dashboard "Live Agent Work" (scans `/proc`)
   - Execute in isolated repos with PTY/background spawns

### What the Dashboard Shows

The master dashboard's **"Live Agent Work"** panel shows:
- **Claude CLI processes** found by scanning `/proc` for running `claude` binaries
- **Kanban "In Progress" cards** from the kanban API
- **Claude Agent Teams** from `~/.claude/teams/`

**It does NOT show:**
- OpenClaw subagents spawned via `sessions_spawn(runtime="subagent")`
- Cron jobs (those are OpenClaw isolated sessions)
- Background Python scripts or other non-Claude processes

---

## How to Monitor Subagents (The Right Way)

### For OpenClaw Subagents (`sessions_spawn` runtime="subagent")

**Use `subagents(action="list")`:**

```python
subagents(action="list")
```

**Returns:**
```json
{
  "status": "ok",
  "action": "list",
  "total": 2,
  "active": [
    {
      "sessionKey": "agent:main:sub:abc123",
      "label": "Fix bug in NQ pipeline",
      "status": "running",
      "startedAt": 1774212000000,
      "model": "nemotron-3-super-120b-a12b"
    }
  ],
  "recent": []
}
```

**Key fields:**
- `active`: Currently running subagents spawned by YOUR session
- `recent`: Completed/failed subagents from last 30 minutes
- `sessionKey`: Use this for `sessions_send` or `sessions_history`

**This is scoped to YOUR session** — you only see subagents YOU spawned, not other agents' subagents.

---

### For Claude CLI Builders (External Coding Agents)

Claude CLI builders are **separate processes**, so OpenClaw subagent tools don't see them.

**Option 1: Check the master dashboard**
- URL: `http://127.0.0.1:8080` (or your dashboard port)
- Look at "Live Agent Work" → shows running `claude` processes
- **Limitation:** Only shows processes while they're running; no history after completion

**Option 2: Query the dashboard API directly**

```bash
curl -s http://127.0.0.1:8080/api/live-work/processes | jq '.agents'
```

**Returns:**
```json
{
  "agents": [
    {
      "pid": 123456,
      "cwd": "/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE",
      "runtime_s": 120,
      "is_subagent": true,
      "model": "nemotron-3-super-120b-a12b",
      "card_title": "Fix ORB strategy bug"
    }
  ]
}
```

**Option 3: Check kanban cards (if using kanban dispatch)**

```bash
curl -s http://127.0.0.1:8787/api/cards?status=In%20Progress | jq '.cards'
```

**Returns:**
```json
{
  "cards": [
    {
      "id": "abc123",
      "title": "Fix bug in NQ pipeline",
      "status": "In Progress",
      "runner_pid": 123456,
      "updated_at": "2026-03-22T13:30:00Z"
    }
  ]
}
```

**Option 4: Check process directly (if you have the PID)**

```bash
ps -p <pid> -o pid,etime,%cpu,%mem,cmd
```

---

## Recommended Workflows

### Scenario 1: Agent Spawns OpenClaw Subagent

**When to use:** Quick isolated tasks (data analysis, config validation, simple fixes)

**How to spawn:**
```python
sessions_spawn(
    task="Analyze the last 100 trades in nq_pipeline.db",
    runtime="subagent",
    mode="run",
    model="nemotron-3-super-120b-a12b"
)
```

**How to monitor:**
```python
# Immediately after spawn
subagents(action="list")

# Later, to check status
result = subagents(action="list")
if result["total"] == 0:
    # Subagent finished — check sessions_list for completed sessions
    sessions_list(kinds=["subagent"], limit=5)
```

**How to get results:**
```python
# Use sessions_yield to pause and wait for completion
sessions_yield(message="Waiting for analysis subagent...")
# Next message will be the subagent's response
```

---

### Scenario 2: Agent Dispatches Claude CLI Builder via Kanban

**When to use:** Coding tasks (feature implementation, bug fixes, refactoring)

**How to spawn:**
```bash
# POST a card to kanban
curl -X POST http://127.0.0.1:8787/api/cards \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Fix ORB strategy bug",
    "description": "The ORB 15min variant is losing money...",
    "status": "Planned",
    "project": "NQ-Trading-PIPELINE"
  }'

# Then trigger the runner
curl -X POST http://127.0.0.1:8787/api/cards/<id>/run
```

**How to monitor:**
```bash
# Check In Progress cards
curl -s http://127.0.0.1:8787/api/cards?status=In%20Progress | jq '.cards[] | {id, title, updated_at}'

# Check specific card status
curl -s http://127.0.0.1:8787/api/cards/<id> | jq '.status, .runner_pid'

# Check live processes (master dashboard API)
curl -s http://127.0.0.1:8080/api/live-work/processes | jq '.agents[] | select(.card_id == "<id>")'
```

**How to get results:**
```bash
# Check card log
cat /home/rob/.openclaw/workspace/kanban-dashboard/logs/<id>.log | tail -50

# Or query final status
curl -s http://127.0.0.1:8787/api/cards/<id> | jq '.status, .completion_note'
```

---

## Common Pitfalls

### ❌ Using `sessions_list` to find Claude CLI builders
**Why it fails:** Claude CLI processes are NOT OpenClaw sessions. They don't appear in the session registry.

**Fix:** Use the dashboard API (`/api/live-work/processes`) or kanban API instead.

---

### ❌ Using `subagents(action="list")` to find other agents' subagents
**Why it fails:** `subagents` is scoped to YOUR session. You can't see another agent's subagents.

**Fix:** Use `sessions_list` to see ALL sessions (including other agents), or use `sessions_send` to ask the other agent directly.

---

### ❌ Expecting finished subagents to stay in `subagents(action="list")`
**Why it fails:** `active` only shows RUNNING subagents. Completed ones move to `recent` for 30 min, then disappear.

**Fix:** Use `sessions_list(kinds=["subagent"], limit=10)` to see completed subagent sessions with history.

---

## Testing: Verified Behaviors (2026-03-22)

### Test 1: `sessions_list` with no filters
**Result:** Returns all sessions (agents, crons, subagents) sorted by `updatedAt` descending.  
**Verified:** ✅ Shows 20 sessions including main agents, cron jobs.

### Test 2: `sessions_list(kinds=["subagent"])`
**Result:** Filter does NOT work — still returns all sessions.  
**Conclusion:** The `kinds` filter may not be implemented yet. Use `sessionKey` pattern matching instead (e.g., `":subagent:"` in key).

### Test 3: `subagents(action="list")` from main session
**Result:** Returns `{"total": 0, "active": [], "recent": []}` when no subagents are running.  
**Verified:** ✅ Correctly scoped to the calling session.

### Test 4: `subagents(action="list")` with active subagent
**Spawned:** `sessions_spawn(task="List 5 recent files", runtime="subagent", mode="run")`  
**Result:** 
```json
{
  "total": 1,
  "active": [{
    "sessionKey": "agent:main:subagent:0fc09ecb-b127-4dd1-84b9-05d698455d8b",
    "label": "List the 5 most recently modified files in /home...",
    "status": "running",
    "runtime": "1m",
    "model": "anthropic/claude-haiku-4-5"
  }]
}
```
**Verified:** ✅ Shows active subagent with sessionKey, label, runtime, model. Perfect for monitoring.

### Test 5: Master dashboard "Live Agent Work"
**Result:** Shows Claude CLI processes from `/proc` scan + kanban In Progress cards.  
**Verified:** ✅ Does NOT show OpenClaw subagents (they're not `claude` processes).

---

## Recommendations for Agent SOUL.md Files

Add this to each agent's workflow documentation:

```markdown
## Monitoring My Subagents

### For OpenClaw subagents (sessions_spawn):
- Check actively running: `subagents(action="list")`
- Check recent history: `sessions_list` and filter by `sessionKey` containing `:sub:`
- Wait for completion: `sessions_yield()` after spawning

### For Claude CLI builders (kanban dispatch):
- Check In Progress: `GET http://127.0.0.1:8787/api/cards?status=In%20Progress`
- Check live processes: `GET http://127.0.0.1:8080/api/live-work/processes`
- Check logs: `cat /home/rob/.openclaw/workspace/kanban-dashboard/logs/<card-id>.log`
```

---

## Summary Table

| Tool | Shows | Scope | Use When |
|------|-------|-------|----------|
| `subagents(action="list")` | Active OpenClaw subagents | YOUR session only | Checking on `sessions_spawn` work |
| `sessions_list` | All sessions (agents, crons, subagents) | Global | Finding completed subagent sessions or other agents |
| Dashboard `/api/live-work/processes` | Running `claude` CLI processes | Global | Checking on coding agents/builders |
| Kanban `/api/cards?status=In Progress` | Active kanban cards | Global | Checking on dispatched coding tasks |

---

## Next Steps

1. **Test with a real subagent spawn** to verify `subagents(action="list")` behavior with active work
2. **Document in each agent's SOUL.md** how to check their specific subagent types
3. **Consider adding a unified "My Work" API** that shows both OpenClaw subagents AND kanban cards for an agent

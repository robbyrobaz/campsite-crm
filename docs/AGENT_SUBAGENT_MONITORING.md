# Agent Subagent Monitoring Guide

**Date:** 2026-03-22  
**Author:** Jarvis (COO)  
**Status:** CANONICAL — all agents must follow this  
**Last Updated:** 2026-03-22 (kanban removed, ACP harness added)

---

## Executive Summary

**Kanban is deprecated.** All agent work uses OpenClaw's native `sessions_spawn`:
- **Quick tasks:** `runtime="subagent"` (data analysis, validation, queries)
- **Coding tasks:** `runtime="acp"` with `agentId="claude-code"` (features, bugs, refactoring)

**Both monitored the same way:** `subagents(action="list")`

---

## How to Spawn Work

### Quick Tasks (< 5 min, single query/analysis)

Use **OpenClaw subagents:**

```python
sessions_spawn(
    task="Count failed trades in the last 24 hours",
    runtime="subagent",
    mode="run",
    model="claude-haiku-4-5"
)
```

**When to use:**
- Database queries ("How many trades in Apex tier?")
- File analysis ("Parse this log for errors")
- Config validation ("Check if systemd unit is valid")
- Quick calculations ("Average PnL over 30 days")

---

### Coding Tasks (features, bugs, refactoring)

Use **ACP harness** (Claude Code, Codex, etc.):

```python
sessions_spawn(
    task="Fix the ORB 15min strategy — it's losing money on low-volume days",
    runtime="acp",
    agentId="claude-code",  # or "codex" depending on config
    mode="run",  # or "session" for persistent/thread-bound
    cwd="/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE",
    runTimeoutSeconds=3600  # 1 hour for complex work
)
```

**When to use:**
- Feature implementation ("Add trailing stop to strategy X")
- Bug fixes ("Fix database lock retry loop")
- Refactoring ("Clean up this 500-line function")
- Multi-file changes across a codebase

**Mode options:**
- `mode="run"` — one-shot task, completes and exits
- `mode="session"` — persistent session (useful for thread-bound Discord/Telegram work)

**Thread-bound sessions:**
```python
sessions_spawn(
    task="Review this PR and suggest improvements",
    runtime="acp",
    agentId="claude-code",
    mode="session",
    thread=True  # creates thread-bound session in Discord/Telegram
)
```

---

## How to Monitor Work

### For ALL OpenClaw Work (subagents + ACP harness)

Use `subagents(action="list")`:

```python
result = subagents(action="list")
```

**Returns:**
```json
{
  "total": 2,
  "active": [
    {
      "sessionKey": "agent:nq:subagent:abc123",
      "label": "Count failed trades in the last 24 hours",
      "status": "running",
      "runtime": "30s",
      "model": "anthropic/claude-haiku-4-5"
    },
    {
      "sessionKey": "agent:nq:acp:def456",
      "label": "Fix the ORB 15min strategy — it's losing...",
      "status": "running",
      "runtime": "5m",
      "model": "claude-code"
    }
  ],
  "recent": []
}
```

**Key fields:**
- `active`: Currently running work spawned by YOUR session
- `recent`: Completed/failed work from last 30 minutes
- `sessionKey`: Use for `sessions_send` or `sessions_history`
- `runtime`: How long it's been running
- `model`: Which model/agent is executing

**This is scoped to YOUR session** — you only see work YOU spawned.

---

### Waiting for Completion

After spawning work, use `sessions_yield()` to pause and wait:

```python
# Spawn work
sessions_spawn(task="...", runtime="subagent", mode="run")

# Pause and wait for completion
sessions_yield(message="Waiting for analysis to complete...")

# Next message will be the completion event
```

**Completion is push-based** — the result arrives as a message. Don't poll with `sessions_list` or `subagents(action="list")`.

---

### Checking on Other Agents' Work

You can't see other agents' subagents via `subagents(action="list")` — it's scoped to your session.

**To check on another agent's work:**
```python
sessions_send(
    sessionKey="agent:crypto:main",
    message="What subagents are you running right now?"
)
```

Or use `sessions_list` to see all sessions globally:
```python
sessions_list(limit=20, messageLimit=0)
# Filter results by sessionKey pattern: ":subagent:" or ":acp:"
```

---

## Master Dashboard Integration

The master dashboard "Live Agent Work" panel shows:
- **Claude CLI processes** from `/proc` scan (legacy, rarely used now)
- **OpenClaw subagents** via `sessions_list` API (NEW — shows all active subagent/acp work)

**URL:** `http://127.0.0.1:8080` (or your configured dashboard port)

---

## Deprecated: Kanban Dispatch

**Kanban is no longer used.** All coding work goes through `sessions_spawn(runtime="acp")`.

**Why kanban was removed:**
- Added unnecessary complexity (extra API, card state management, log files)
- Duplicate monitoring (kanban API + OpenClaw sessions)
- `sessions_spawn` provides the same capability natively

**If you see kanban references in old code/docs, ignore them.**

The kanban codebase remains in the repo for potential future use, but it is NOT part of the active workflow.

---

## Common Workflows

### Scenario 1: Agent Needs Quick Data Analysis

```python
# Spawn subagent
sessions_spawn(
    task="Query nq_pipeline.db and return the top 5 strategies by profit factor",
    runtime="subagent",
    mode="run",
    model="claude-haiku-4-5"
)

# Wait for result
sessions_yield()

# Result arrives as next message
```

---

### Scenario 2: Agent Needs to Fix a Bug

```python
# Spawn ACP harness
sessions_spawn(
    task="""
    The ORB 15min strategy in NQ-Trading-PIPELINE is losing money.
    Debug the entry logic and fix the issue. Test with backtest data before committing.
    """,
    runtime="acp",
    agentId="claude-code",
    mode="run",
    cwd="/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE",
    runTimeoutSeconds=1800  # 30 min
)

# Check status (optional)
result = subagents(action="list")
if result["total"] > 0:
    print(f"Builder running: {result['active'][0]['runtime']}")

# Wait for completion
sessions_yield(message="Waiting for bug fix...")
```

---

### Scenario 3: Agent Wants to Check on All Active Work

```python
# List all your subagents/builders
result = subagents(action="list")

for agent in result["active"]:
    print(f"[{agent['runtime']}] {agent['label']}")

# Example output:
# [2m] Fix ORB strategy bug
# [30s] Count Apex tier models
```

---

## Common Pitfalls

### ❌ Spawning ACP harness without `agentId`
**Error:** `runtime="acp"` requires `agentId` unless `acp.defaultAgent` is configured.

**Fix:**
```python
sessions_spawn(
    task="Fix bug",
    runtime="acp",
    agentId="claude-code",  # REQUIRED
    mode="run"
)
```

---

### ❌ Using `sessions_list` to monitor your own subagents
**Why it fails:** `sessions_list` shows ALL sessions globally. You want `subagents(action="list")` which is scoped to YOUR work only.

**Fix:** Use `subagents(action="list")` instead.

---

### ❌ Polling for completion
**Why it fails:** Completion is push-based. After spawning, use `sessions_yield()` to wait.

**Wrong:**
```python
sessions_spawn(task="...", ...)
while True:
    result = subagents(action="list")
    if result["total"] == 0:
        break
    time.sleep(5)
```

**Right:**
```python
sessions_spawn(task="...", ...)
sessions_yield()  # Completion arrives as next message
```

---

### ❌ Expecting finished work to stay in `subagents(action="list")`
**Why it fails:** `active` only shows RUNNING work. Completed work moves to `recent` for 30 min, then disappears.

**Fix:** After completion, the result is delivered as a message. Don't poll for it.

---

## Testing: Verified Behaviors (2026-03-22)

### Test 1: `sessions_list` with no filters
**Result:** Returns all sessions (agents, crons, subagents, acp) sorted by `updatedAt` descending.  
**Verified:** ✅ Shows 20 sessions including main agents, cron jobs.

### Test 2: `sessions_list(kinds=["subagent"])`
**Result:** Filter does NOT work — still returns all sessions.  
**Conclusion:** The `kinds` filter may not be implemented yet. Use `sessionKey` pattern matching instead (e.g., `":subagent:"` or `":acp:"` in key).

### Test 3: `subagents(action="list")` from main session
**Result:** Returns `{"total": 0, "active": [], "recent": []}` when no work is running.  
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
**Result:** Shows Claude CLI processes from `/proc` scan (legacy).  
**Verified:** ✅ Does NOT show OpenClaw subagents (need to add API endpoint).

---

## Summary Table

| Tool | Shows | Scope | Use When |
|------|-------|-------|----------|
| `subagents(action="list")` | All YOUR active work (subagent + acp) | YOUR session only | Default monitoring method |
| `sessions_list` | All sessions globally (agents, crons, subagents, acp) | Global | Finding other agents' sessions |
| `sessions_send` | Send message to another agent | Cross-agent | Asking another agent about their work |
| `sessions_yield` | Pause and wait for completion | Current session | After spawning work |
| Dashboard "Live Agent Work" | Claude CLI processes + OpenClaw sessions (NEW) | Global | Visual overview of all active work |

---

## Next Steps for Agents

1. **Update your SOUL.md** with delegation strategy:
   ```markdown
   ## Delegation
   - Quick tasks: `sessions_spawn(runtime="subagent")`
   - Coding tasks: `sessions_spawn(runtime="acp", agentId="claude-code")`
   - Monitor: `subagents(action="list")`
   ```

2. **Remove all kanban references** from your workflow docs

3. **Test ACP harness** with a simple coding task to verify it works in your environment

4. **Use `sessions_yield()` after spawning** — don't poll for completion

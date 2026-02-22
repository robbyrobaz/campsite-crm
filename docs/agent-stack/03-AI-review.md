# Phase 3 — Critical Review of Agent Stack PRD
**Reviewer:** Jarvis subagent (adversarial mode)  
**Date:** 2026-02-19  
**Source documents:** `01-research.md`, `02-PRD-draft.md`, `AGENTS.md`, `SOUL.md`  
**Verdict:** Proceed with a significantly trimmed scope. The PRD has real value in 3 places and unnecessary complexity in 5.

---

## Executive Summary

The PRD is well-researched and internally consistent, but it has a structural problem: it's designing a system for a 5-person engineering team being run by one person on one laptop. The most valuable parts (formalized agent files, enforcement hooks) are buried under orchestration complexity that introduces more failure modes than it solves. The kanban server as central infrastructure and the always-on QA Sentinel gate are the two biggest over-reaches. More critically, the hook implementation as written **will not work** because it references Claude Code hook environment variables that don't exist.

Start with what's unambiguously good, kill what's overkill, and fix the technical errors before touching a single config file.

---

## 1. Feasibility — What Actually Breaks

### 1.1 The Hook Scripts Are Broken As Written

This is the biggest technical error in the PRD. Every hook script references `CLAUDE_TOOL_ARGS` and `CLAUDE_TOOL_RESULT_PATH` as environment variables:

```bash
COMMAND="${CLAUDE_TOOL_ARGS:-}"
FILE="${CLAUDE_TOOL_RESULT_PATH:-}"
```

**These environment variables do not exist in Claude Code's hook system.** The Claude Code hook system delivers tool call context via **stdin as a JSON payload**, not through environment variables. The correct pattern is:

```bash
# Correct: read from stdin
TOOL_INPUT=$(cat)
COMMAND=$(echo "$TOOL_INPUT" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('command', ''))")
```

Without this fix, every hook script will silently receive an empty string for `COMMAND` and `FILE`, match nothing, and exit 0 — meaning **all enforcement is a no-op**. You'll think you have guards; you won't.

The research section (§6 in the research doc) describes hook behavior correctly, but the PRD's implementation section skipped the actual hook API. This needs to be verified against the current Claude Code version before any hooks go live.

### 1.2 The COO Architecture Is Self-Contradicting

The PRD defines `coo.md` as a `.claude/agents/` file — a subagent definition. But Jarvis **is** the main session. Rob talks to the main session directly. Creating a `coo.md` subagent implies there's a parent entity above the COO who decides when to invoke it, but no such parent is defined. 

If `coo.md` is meant to replace or formalize SOUL.md, say so. If it's meant to be invoked as a subagent from the main session... who invokes it? This is architecturally undefined.

The `disallowedTools: Write, Edit` in `coo.md` only applies when the COO runs **as a subagent**. When Jarvis operates as the main session (which is 100% of current usage), this restriction does nothing. The PRD's core enforcement premise for the COO is therefore only effective if the architecture fundamentally changes how Rob interacts with Jarvis — and that change is never explicitly called out.

### 1.3 MCP Server Inheritance — The Single-Writer Rule Has a Hole

The PRD says specialists won't have `dynamic-kanban` in their `mcpServers:` frontmatter, enforcing single-writer access. However, the Claude Code docs say that if you list `mcpServers:` in subagent frontmatter, you get those servers. If you **omit** the field, behavior is **inherit from parent session**.

If `dynamic-kanban` is registered in `~/.claude/mcp.json` (the main session's MCP config), all subagents without an explicit `mcpServers:` override will inherit it. The specialists as written in the PRD don't include `mcpServers:` in their frontmatter — meaning they may inherit the kanban server. The PRD assumes omitting the field means "none." It likely means "all." Verify this before shipping.

### 1.4 `~/.claude/mcp.json` Is Not a Standard Path

The PRD specifies `~/.claude/mcp.json` as the MCP config file. This isn't the standard Claude Code MCP config path. MCP servers are registered via `claude mcp add` (which modifies `~/.claude/claude_desktop_config.json`) or via project-level `.claude/settings.json`. The correct path needs to be verified in the current OpenClaw/Claude Code version. If you write to the wrong path, the kanban MCP server never loads and everything fails silently.

### 1.5 The Kanban State File Migration Is a Maintenance Trap

The PRD recommends storing kanban state in `brain/kanban/` (Q2 recommendation: Option B). This requires modifying `config.py` in the upstream `dynamic-kanban-mcp` repo. That means either forking the repo or patching it. Now you own a fork. The upstream can update; your fork diverges. This is a maintenance burden the PRD doesn't account for. If you want brain/kanban/ state, the cleaner approach is a symlink or an env var if the kanban server supports configuring paths via env (check before modifying source).

---

## 2. Complexity vs. Value — The Honest Accounting

### What's genuinely worth the complexity

**Formalized agent files (`.claude/agents/*.md`):** High value, low risk. Versioned specialist definitions with explicit tool restrictions and model assignments stop you from paying Opus rates for haiku-tier tasks and stop specialists from accidentally having Write access when they shouldn't. This should be done.

**Enforcement hooks (if the implementation is correct):** High value. SOUL.md says "don't do X" and relies on the model complying. A hook physically blocks it. The concept is right. The implementation needs fixing (§1.1).

**QA Sentinel as a named agent:** Medium value. Formalizing the review step is good. What's questionable is making it a hard gate on every task.

### What's over-engineered for one laptop

**The kanban MCP server as always-on infrastructure:** This is a persistent Python process, a WebSocket server, file-based JSON state, and a browser tab. For a solo operator, `brain/status/status.json` is already doing most of this job. The kanban adds a visual board (genuinely nice) and dependency tracking (useful for complex projects). But ask whether Rob will actually watch the kanban board in a browser tab. If the answer is "probably not regularly," you've added infrastructure for a feature that won't be used.

**The QA Sentinel on every output with Opus:** Every specialist task goes through QA before delivery. QA uses Opus. Cost scenario: crypto-researcher (sonnet, ~$0.50 for a report) → QA Sentinel (opus, ~$1.50 for validation) → delivery. You've tripled the cost of a research report to have an Opus instance confirm the Sonnet instance did its job. For code changes, QA is justified. For a daily market research report or a heartbeat check, it's wasteful. The PRD's own Q1 acknowledges this and recommends "COO judgment" — which means the hard gate is already being softened before it's built.

**The "continuous task pump" (§5.4):** Auto-dispatching specialists whenever backlog isn't empty, without waiting for Rob, is a recipe for burning tokens on tasks Rob may no longer want. The current setup requires Rob to initiate tasks, which is a feature, not a bug. Rob is running active ML experiments (the Numerai full run is live as I write this). An autonomous task pump could spawn a devops-engineer to restart a service at the same time the ml-engineer is mid-pipeline. The PRD has no interlock for this.

**Six (or seven) distinct personas:** Rob's work currently decomposes into: research, ML/quant code, dashboard/UI, infra, general Python. That's 5 specialists. The PRD adds python-pro as distinct from ml-engineer. For one person's projects, the boundary between "pure Python backend" and "Python ML work" is often blurry. The Blofin dashboard has Flask (python-pro territory) calling ML models (ml-engineer territory) reading from SQLite (python-pro?). Maintaining clear persona boundaries in practice requires Rob and Jarvis to always agree on which persona handles what. That coordination cost adds up.

**The `coo.md` agent file:** Duplicates large sections of SOUL.md and AGENTS.md. The session startup sequence, specialist routing guide, and prohibited actions list all already exist. If the goal is adding `disallowedTools` and `mcpServers` fields to Jarvis, you can achieve that through settings.json hooks at the session level without creating a whole new agent file that conflicts with the existing identity documents.

---

## 3. Risk — What Breaks First

### 3.1 Hook Failure Is Silent

If the hook scripts are wrong (§1.1), every hook exits 0 and enforcement silently evaporates. You'll believe the system is guarded; it isn't. There's no test for "did the hook actually fire and evaluate the command?" before going live. Add a smoke test: a hook that logs every invocation to a file. If the log is empty after a week, the hooks aren't running.

### 3.2 Specialist Context Exhaustion Has No Recovery Path

`maxTurns: 40` for ml-engineer. The Numerai codebase is large. A 40-turn exploration + implementation on a complex backtesting task will approach context limits. When a specialist hits the context ceiling or maxTurns, it stops with no completion report. The kanban card stays "Delegated" forever. No retry logic exists. No heartbeat checks for stuck cards (Q8 is unresolved). This will happen. What's the manual recovery? The PRD doesn't say.

### 3.3 Concurrent Specialists + No Worktree Isolation

The PRD explicitly defers worktree isolation (Q7: "low risk for current patterns"). But the continuous task pump (§5.4) can dispatch multiple specialists simultaneously — it explicitly does NOT wait. If ml-engineer and dashboard-builder are both working on the Blofin stack (which they often do — ML writes data, dashboard reads it), concurrent writes to overlapping files are a real possibility. The "low risk for current patterns" assessment assumes sequential execution, but the PRD's automation layer creates parallel execution.

### 3.4 The Kanban Server Is a New Single Point of Failure

COO can't track tasks if the kanban MCP isn't running. If the server crashes (OOM, Python exception, WebSocket disconnect), the COO's tool calls to `kanban_status()` and `kanban_move_card()` return errors. The COO has no fallback behavior defined for "kanban unavailable." The PRD says to optionally add systemd auto-restart, but marks this optional. For a dependency this central, it should be mandatory from day one.

### 3.5 The COO Rogue Scenario

The blast radius if the COO goes off-script: it can write to `brain/`, `docs/`, `memory/` (explicitly permitted), spawn all specialists, and send Telegram messages to Rob. The kanban single-writer rule means COO can also create misleading kanban state (move cards to Done without QA). Since the QA gate is convention-based, not technical, a confused or misdirected COO session could spam Rob with un-reviewed output, fill the kanban board with ghost tasks, or trigger specialists on tasks Rob never requested (via the task pump). This is a real scenario during context degradation in long sessions.

---

## 4. Gaps the PRD Doesn't Address

### 4.1 No Cost Tracking

No budget cap, no token count per agent, no alerting when a task costs > $N. The QA Sentinel at Opus rates + continuous task pump = potential for expensive runaway sessions. Current OpenClaw setup has no cost controls either, but the new architecture amplifies the risk with automation.

### 4.2 API Keys Across Agents

How does crypto-researcher get the API keys it needs for price data? How does ml-engineer access Numerai credentials? The PRD's post-write hooks scan for hardcoded secrets, but nothing addresses how agents *legitimately* get secrets they need for their work. If the answer is "environment variables in the subagent config," that needs to be specified. If the answer is "read from a config file that's not in git," that needs to be specified.

### 4.3 Agent-Level Logging

No audit log of what each agent actually did. You'll have kanban state (card moved from A to B) but not "ml-engineer ran pytest, got these errors, retried, modified these 3 files." The `~/.claude/projects/{project}/{sessionId}/subagents/` transcripts exist but aren't aggregated or searchable. For post-mortem analysis when something goes wrong, you're flying blind.

### 4.4 Stale Kanban State

If the kanban server crashes and restarts, does it correctly reload the JSON state? The research says "backup/restore" for atomic operations, but doesn't confirm that a mid-crash restart recovers cleanly. If the JSON is corrupted or half-written, the board comes back in an unknown state. No recovery runbook is provided.

### 4.5 What Happens to the Current In-Progress Numerai Task?

The current `status.json` has an active task: `numerai-era-boost-full` assigned to `jarvis-direct`, process ID `clear-tidepool`. The migration plan says "add kanban for active task work" but doesn't address how currently active tasks transition. Do they get manually entered into the kanban? Does status.json tracking just continue until the migration is complete? The PRD implies a clean-slate migration but reality has work in flight.

### 4.6 Background Subagents Can't Use MCP

The research (§6) clearly states: "Background subagents cannot use MCP tools." The PRD proposes specialists use `memory: project` (which requires Write access to agent memory) and potentially MCP tools. If specialists run in background mode (which happens when you want parallel execution), they silently lose MCP access. No mention of this constraint anywhere in the PRD.

---

## 5. Alternatives — What Gets 80% of the Value at 20% of the Complexity

### The Minimal Effective Upgrade (Recommended)

**Step 1: Create agent files. Full stop.**

Drop 5-6 `.md` files into `~/.claude/agents/` (not project-local). This gives you versioned specialists with explicit tool restrictions and model assignments. Zero new infrastructure, zero new processes. This is the single highest-value change in the entire PRD.

Time: 1-2 hours. Risk: near zero. Value: high.

**Step 2: Fix hooks, but globally and simply.**

Instead of per-agent hook scripts that require the non-existent `CLAUDE_TOOL_ARGS` pattern, implement **one global PreToolUse hook** in `settings.json` that catches obviously destructive patterns (rm -rf, force push, DROP TABLE) across all sessions. Keep it simple: stdin JSON parsing, 20 lines of bash, one audit log file. Test it before trusting it.

Time: 2-3 hours (including testing). Risk: medium (hook API needs verification).

**Step 3: Add the QA Sentinel as a named agent, not a hard gate.**

Create `qa-sentinel.md` as a subagent file. Use it. But don't make it a mandatory kanban step. Keep the convention from SOUL.md ("never deliver unreviewed work") and formalize it by having a named agent with the right prompt. The hard gate can come later if the convention proves unreliable.

Time: 30 min. Risk: zero.

**What to skip entirely (or phase to later):**

- **The kanban MCP server** — skip for now. Status.json + GitHub issues already handle this. Revisit if Rob explicitly wants task visualization.
- **The continuous task pump** — skip. Keep Rob as the trigger for task initiation. Automation without human intent confirmation is dangerous for active ML experiments.
- **Ruflo v3alpha** — skip. v3alpha + 340MB install + API instability on an always-on laptop is not worth the memory features.
- **python-pro as a separate persona** — skip. Collapse into ml-engineer with a broader scope, or create it when there's actually a project that needs it.

---

## 6. Ubuntu-Specific Concerns

**Port 8765** — No conflict check in the PRD. Verify: `ss -tlnp | grep 8765` before installing. Minor, but skip this and you'll spend time debugging a silent port conflict.

**The systemd unit** — The unit file is correct (system-level service with `User=rob`). However, the `WorkingDirectory` is `/home/rob/tools/kanban` which means the kanban data files live next to the code, not in the workspace. This conflicts with the Q2 recommendation of `brain/kanban/`. Pick one and commit.

**WebSocket binding** — The default is `0.0.0.0`. The PRD's MCP config sets `KANBAN_WEBSOCKET_HOST=127.0.0.1` as an env var override. Confirm the kanban server actually reads this env var — the research shows the env var table but the actual code behavior needs verification. If it ignores the env var, the kanban WebSocket is exposed on all interfaces with no auth.

**ruff and trash-cli** — Both are assumed available in hook scripts and agent prompts. Neither is installed by default on Ubuntu. The hooks gracefully degrade (`command -v ruff` check), but the devops-engineer prompt says to use `trash` without any fallback if it's not installed. Add a setup step: `sudo apt install trash-cli python3-pip && pip3 install ruff`.

**Node.js v22 is fine** for Ruflo (needs v20+), confirmed from runtime. Not a concern.

**The laptop-as-always-on-server concern** — Adding a persistent Python WebSocket server + file watcher to omen-claw's background process list is a minor resource hit. Not a deal-breaker but worth noting: omen-claw already runs blofin-dashboard, blofin-ingestor, blofin-paper, OpenClaw gateway, and the Numerai full-dataset run. Adding kanban-mcp to that is fine, but this machine isn't a clean lab environment — things are running. Any new service should be isolated and monitored by the heartbeat.

---

## 7. Current Setup Comparison — What the PRD Misses

### The PRD undersells what already works

The research section is honest about this (§7 of research doc), but the PRD proper treats the existing setup as mostly deficient. In reality:

**SOUL.md already has:**
- "Never deliver unreviewed work" — that's the QA gate
- "Act first, report after" — that's the continuous task pump logic
- "Infrastructure changes — do it, notify Rob after" — that's the devops-engineer permission model
- "Destructive actions — think twice, confirm" — that's the bash guard

**AGENTS.md already has:**
- Full model routing table (opus/sonnet/haiku/mini/codex)
- "Each builder gets ONE task, ONE repo scope" — that's the specialist scoping
- "Builders report to Jarvis, never to Rob" — that's the single interface principle
- "Review Builder output before delivering" — that's the QA gate again
- "Plan before spawning — never spawn in loops" — that's the anti-pump guard

**What the PRD is adding to these is:** enforcement that can't be argued around, and a kanban for visibility. Everything else is reformatting what already exists into `.md` files with frontmatter.

This matters because: **the PRD could create confusion**. If SOUL.md says one thing and `coo.md` says another, which wins? If AGENTS.md has a routing table and `coo.md` has a different one, what does Jarvis follow? The PRD never resolves this. The intent seems to be "update AGENTS.md and SOUL.md" (§6.2) but the actual content updates aren't shown — just agent files that duplicate the same information in different format.

### The Migration Creates a Consistency Problem

The PRD says to update SOUL.md and AGENTS.md. But then you have:
- SOUL.md — Jarvis's identity and constraints (instructional)
- AGENTS.md — Operating manual with model routing and subagent discipline (instructional)
- `coo.md` — COO identity and constraints (instructional + frontmatter enforcement)

Two of these three are now saying the same things in different formats. One of them has actual `disallowedTools` enforcement. That inconsistency will cause confusion when SOUL.md says "you can do X" and `coo.md`'s frontmatter says `disallowedTools: Write, Edit`. The solution is to be explicit: `coo.md` replaces the constraint sections of SOUL.md for the primary session, not supplements them.

---

## Summary Verdict

| Component | Verdict | Reason |
|-----------|---------|--------|
| Formalized agent files (`.claude/agents/`) | ✅ **Do it** | High value, low risk, zero new infrastructure |
| QA Sentinel as named agent | ✅ **Do it** | Good prompt engineering, no overhead if used by convention |
| Enforcement hooks (concept) | ✅ **Do it, but fix the implementation** | Hook env var approach is broken; needs stdin JSON parsing |
| Dynamic Kanban MCP server | ⚠️ **Defer** | Adds infrastructure complexity; status.json mostly handles this already |
| Continuous task pump | ❌ **Skip** | Dangerous for active ML work; keeps running without Rob's intent |
| QA gate as hard kanban lock | ❌ **Skip (Phase 1)** | Convention-based is fine; hard gate is premature |
| Ruflo v3alpha | ❌ **Skip** | v3alpha, heavy install, solves a problem you don't have yet |
| python-pro as separate persona | ⚠️ **Maybe** | Create it when there's a clear project for it, not speculatively |
| coo.md replacing SOUL.md for COO constraints | ⚠️ **Clarify** | Architecture of who invokes the COO subagent needs resolution |
| Worktree isolation | ⚠️ **Revisit when parallel specialists are actually needed** | Not needed for sequential patterns, but add it before enabling the task pump |

**Recommended first action:** Verify the Claude Code hook stdin/JSON API on the current version before writing a single hook script. Everything else is negotiable. The hooks are the PRD's core value-add, and they're currently broken.

---

*Review complete. Total issues flagged: 4 critical (hook API, COO architecture, MCP inheritance, config path), 5 design concerns, 6 gaps. Recommended scope reduction: ~40% of PRD complexity delivers ~85% of the stated value.*

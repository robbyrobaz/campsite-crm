# Agent Context Protocol — Universal System for All Agents

**Created:** 2026-03-28  
**Purpose:** Ensure every agent session starts with complete, current context

---

## The Problem

New agent sessions wake up "fresh" with no memory of previous work. Without a systematic approach, agents:
- Miss recent findings and fixes
- Repeat failed approaches
- Lack awareness of current state
- Ask redundant questions

---

## The Solution (4 Components)

### 1. **Workspace Files = Source of Truth**

Each agent has an isolated workspace with core identity files:

**Jarvis (COO):** `/home/rob/.openclaw/workspace/`
**NQ Agent:** `/home/rob/.openclaw/workspace-nq/`
**Crypto Agent:** `/home/rob/.openclaw/workspace-crypto/`
**SP Agent:** `/home/rob/.openclaw/workspace-sp/`
**Church Agent:** `/home/rob/.openclaw/workspace-church/`

**Core files (every agent):**
- `SOUL.md` — Who you are (identity, role, directives)
- `AGENTS.md` — Operating manual (session checklist, workflows)
- `IDENTITY.md` — Name, role, emoji
- `BOOTSTRAP.md` — Current state (services, counts, active issues) **← Updated frequently**
- `MEMORY.md` — Long-term learnings (patterns, lessons, preferences)
- `memory/YYYY-MM-DD.md` — Daily notes (what happened today/yesterday)

**Why workspace files:**
- ✅ No symlinks (fragile, break on git ops)
- ✅ Works for agents without repos (Jarvis, Church)
- ✅ Git backup hygiene commits changes hourly
- ✅ Each agent fully isolated (no context bleeding)

---

### 2. **Mandatory Session Startup Checklist**

**AGENTS.md already defines this — enforcement is the issue.**

**Auto-injected by OpenClaw (do NOT re-read):**
AGENTS.md, SOUL.md, TOOLS.md, IDENTITY.md, USER.md, HEARTBEAT.md, BOOTSTRAP.md, MEMORY.md

These are in the system prompt under "Project Context" before the agent makes any tool calls.

**Must READ with tool (not auto-injected):**
1. `brain/CHECKLIST.md` — operating checklist
2. `brain/PROJECTS.md` — project board
3. `brain/status/status.json` — current tasks
4. `memory/YYYY-MM-DD.md` — Today's notes
5. `memory/YYYY-MM-DD.md` (yesterday) — Yesterday's notes

**Enforcement mechanism:**
- BOOTSTRAP.md timestamp visible in Project Context — verify <24h, update silently if stale
- Do NOT narrate startup steps to the user

---

### 3. **Structured Updates (Write-Once, Read-Everywhere)**

**BOOTSTRAP.md format:**
```markdown
# BOOTSTRAP.md - [Agent Name] Current State

**Last updated:** 2026-03-28 07:40 MST
**Session:** [Brief one-liner of what you're working on]

## Current State

### Services
- service-name.service: active/inactive, last checked [time]
- ...

### Counts
- Strategies: X live, Y FT, Z BT-only
- Models: X trained, Y deployed
- ...

### Active Issues
- Issue description (started YYYY-MM-DD, status: investigating|blocked|resolved)
- ...

### Recent Changes (Last 24h)
- Change description (YYYY-MM-DD HH:MM)
- ...
```

**Update triggers:**
- End of major work session
- After service changes (restart, config edit)
- After discovering issues
- After deploying fixes
- Before handing off to Rob

**Why this format:**
- ✅ Timestamp shows freshness
- ✅ Services section = current health
- ✅ Counts = quick validation
- ✅ Active issues = what needs attention
- ✅ Recent changes = what just happened

---

### 4. **Daily Memory Files (Already Working)**

`memory/YYYY-MM-DD.md` — Chronological log of today's work

**Format:**
```markdown
# 2026-03-28 - [Agent Name]

## [HH:MM] Session Started
Brief summary of what this session is about

## [HH:MM] Finding: [Title]
What we discovered, how we found it, what we did

## [HH:MM] Fix Applied: [Title]
What was broken, what we changed, validation steps

## [HH:MM] Next Steps
What needs to happen next
```

**Why daily files:**
- ✅ Chronological (easy to trace timeline)
- ✅ Auto-created by git backup hygiene
- ✅ Searchable (grep, memory_search)
- ✅ Never stale (today = current work)

---

## Agent Startup Flow

**Auto-injected (already in prompt — skip):** SOUL.md, AGENTS.md, IDENTITY.md, USER.md, TOOLS.md, HEARTBEAT.md, BOOTSTRAP.md, MEMORY.md

**Read with tool:**
1. brain/CHECKLIST.md — operating rules
2. brain/PROJECTS.md — project board
3. brain/status/status.json — current tasks
4. memory/YYYY-MM-DD.md (today + yesterday) — daily notes

**Verify:** BOOTSTRAP.md timestamp (visible in Project Context) <24h? If stale, update silently.

**Now agent knows:**
- Who they are (SOUL — auto-injected)
- Current state (BOOTSTRAP — auto-injected)
- What happened recently (daily memory — read)
- Patterns and lessons (MEMORY — auto-injected)
- Operating rules (CHECKLIST — read)

---

## Failure Modes & Fixes

### Problem: BOOTSTRAP.md is stale (>24h old)
**Detection:** Agent checks timestamp header  
**Action:** Agent updates BOOTSTRAP by checking current state (services, counts)  
**Prevention:** Update BOOTSTRAP at end of every session

### Problem: Daily memory missing
**Detection:** File doesn't exist for today  
**Action:** Create it with session start entry  
**Prevention:** Git backup hygiene auto-creates

### Problem: Agent skips checklist
**Detection:** Agent asks questions answered in BOOTSTRAP/MEMORY  
**Action:** Rob calls it out, agent re-reads files  
**Prevention:** System prompt enforcement (already exists)

### Problem: Context bleeding (one agent's BOOTSTRAP in another's workspace)
**Detection:** SOUL.md identity mismatch  
**Action:** Verify workspace path matches agent identity  
**Prevention:** Isolated workspaces (already working)

---

## What We DON'T Need

❌ **Symlinks** — Fragile, break on git ops, add complexity  
❌ **Verification scripts** — Overkill, agents read files anyway  
❌ **Session summaries** — Daily memory already does this  
❌ **Repo coupling** — Not all agents have repos  
❌ **Manual sync steps** — Git backup hygiene auto-commits

---

## Migration Plan (Minimal Changes)

### For All Agent Workspaces:
1. ✅ **BOOTSTRAP.md** — Add "Last updated" timestamp header
2. ✅ **MEMORY.md** — Add "Last updated" header
3. ✅ **Daily memory** — Already working, keep using

### For Agent Behavior:
1. ✅ **Enforce checklist** — Already in system prompt, just follow it
2. ✅ **Update BOOTSTRAP** — After major work, before handoff
3. ✅ **Write daily memory** — Log findings/fixes as they happen

### No Changes Needed:
- ✅ Isolated workspaces (already working)
- ✅ Git backup hygiene (already committing hourly)
- ✅ AGENTS.md checklist (already defined)

---

## Validation (How to Test)

**Spawn fresh agent session:**
1. Check BOOTSTRAP timestamp (<24h?)
2. Check MEMORY timestamp
3. Check today's daily memory exists
4. Agent should know current state without asking

**If agent asks "what's the current state?":**
- ❌ FAILED — agent skipped checklist
- ✅ PASS — agent knows from BOOTSTRAP

---

## Summary

**Current system (90% working):**
- Workspace files exist
- Checklist exists
- Daily memory works
- Git backup works

**Missing 10%:**
- Timestamp headers (add now)
- Consistent BOOTSTRAP updates (enforce)
- Checklist enforcement (follow it!)

**NQ Agent's symlink/verification approach:**
- Over-engineered
- Fragile (symlinks break)
- Repo-dependent (doesn't work for all agents)
- Solves wrong problem (agents not reading files, not files being stale)

**This protocol:**
- Simple (add timestamps, update BOOTSTRAP)
- Universal (works for all agents)
- Robust (no symlinks, no scripts)
- Already 90% deployed

---

**Next step:** Add timestamp headers to all agent BOOTSTRAP.md files, commit, done.

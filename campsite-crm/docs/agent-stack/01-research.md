# Phase 1 — Deep Research: Multi-Agent Architecture Tools

**Compiled:** 2026-02-19  
**Purpose:** Evaluate external tools for building a COO→specialist agent stack on top of the current Jarvis/OpenClaw setup.  
**Sources:** Live README fetches from GitHub + official Anthropic docs + current workspace files.

---

## Table of Contents

1. [Dynamic Kanban MCP](#1-dynamic-kanban-mcp)
2. [Claude-Flow / Ruflo v3](#2-claude-flow--ruflo-v3)
3. [The Claude Protocol](#3-the-claude-protocol)
4. [Awesome Claude Code Subagents](#4-awesome-claude-code-subagents)
5. [Beads Kanban UI](#5-beads-kanban-ui)
6. [Claude Code Native Subagents](#6-claude-code-native-subagents)
7. [Claude Code Agent Teams](#7-claude-code-agent-teams)
8. [Current Jarvis/OpenClaw Setup](#8-current-jarvisopenflow-setup)
9. [Specific Questions Answered](#9-specific-questions-answered)
10. [Synthesis: How They Work Together](#10-synthesis-how-they-work-together)
11. [Recommendation Matrix](#11-recommendation-matrix)

---

## 1. Dynamic Kanban MCP

**Repo:** `renatokuipers/dynamic-kanban-mcp`  
**Version:** v3.0 (production-ready claim)  
**License:** Not stated in README (assume MIT based on typical OSS)  
**Language:** Python 3.7+  
**Dependencies:** `websockets`, `pydantic`

### Architecture

```
Claude (MCP client)
       │
       ▼ JSON-RPC 2.0
  mcp-kanban-server.py
       │
       ▼ WebSocket (port 8765)
  kanban-board.html  ←── Browser (human monitor)
```

**Files:**
- `mcp-kanban-server.py` — MCP entrypoint, JSON-RPC 2.0
- `kanban_controller.py` — Core logic, mode management, atomic operations
- `mcp_protocol.py` — MCP protocol implementation
- `models.py` — Pydantic models (Task, ProjectConfig, BoardConfig, ProgressData, etc.)
- `config.py` — Centralized config + env vars
- `kanban-board.html` / `kanban-board.js` — Pre-built UI

### Dual-Mode System

| Mode | Who controls | Claude actions |
|------|-------------|----------------|
| **Autonomous** (default) | Claude | Execute immediately; UI syncs in real-time |
| **Manual** | Human via browser | Claude actions **queued and blocked** |

When switching Manual→Autonomous: user can apply or clear queued Claude actions. This prevents human-AI write conflicts.

### MCP Tools (15+)

**Project:** `create_project`, `add_feature`, `configure_board`, `import_features`  
**Kanban ops:** `kanban_status`, `kanban_get_ready_tasks`, `kanban_get_next_task`, `kanban_move_card`, `kanban_update_progress`  
**Sessions:** `kanban_start_session`, `kanban_end_session`, `analyze_task_requirements`, `get_task_details`  
**Validation:** `validate_dependencies`, `validate_project_dependencies`

### Data Model

- **Task:** UUID-based IDs, priority (low/medium/high/critical), effort (xs/s/m/l/xl), status (backlog/ready/progress/testing/done), dependencies with circular-detection, acceptance criteria
- **Persistence:** `kanban-progress.json` (board state), `features.json` (feature definitions)
- **Atomic operations:** Backup/restore prevents corruption

### Config Schema (MCP integration)

```json
{
  "mcpServers": {
    "dynamic-kanban": {
      "command": "python3",
      "args": ["./mcp-kanban-server.py"],
      "env": {},
      "description": "Dynamic Kanban MCP Server v3.0"
    }
  }
}
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `KANBAN_WEBSOCKET_PORT` | 8765 | WebSocket port |
| `KANBAN_WEBSOCKET_HOST` | 0.0.0.0 | WebSocket host |
| `KANBAN_RECONNECT_DELAY` | 3000ms | Reconnect delay |
| `KANBAN_MAX_RECONNECTS` | 10 | Max reconnect attempts |

### Failure Modes & Limitations

- **Multi-agent concurrent writes:** NOT explicitly handled. The README mentions "thread-safe atomic operations" and UUID-based IDs to prevent duplicates, but this appears to address single-agent + file-lock safety, NOT concurrent multi-agent scenarios. If two agents call `kanban_move_card` simultaneously, behavior is undefined by the docs. The mode system (Autonomous/Manual) is for human vs. AI conflict prevention only.
- **No distributed lock:** State lives in a local JSON file. No Redis, no CRDT, no distributed coordination.
- **Runs locally only:** WebSocket on `0.0.0.0` — fine for local dev, would need proxying for remote.
- **Single project per server instance:** The state file path is hardcoded per-server — multiple projects need multiple instances.
- **No auth on WebSocket:** Anyone on the local network who knows the port can connect the UI.
- **Alpha/v3.0 stability:** "Production-ready" is the claim but there are no test files mentioned in the README.

### Ubuntu Install Notes

Straightforward: `pip install websockets pydantic`, run `python3 mcp-kanban-server.py`. No platform-specific issues.

---

## 2. Claude-Flow / Ruflo v3

**Repo:** `ruvnet/claude-flow`  
**Package name:** `ruflo` (npm)  
**Version:** v3alpha (explicitly alpha)  
**License:** MIT  
**Language:** Node.js (TypeScript)  
**Prerequisites:** Node.js 20+, npm 9+, Claude Code installed first

### What It Actually Is

Ruflo is an **MCP server** that you add to Claude Code via `claude mcp add ruflo`. It provides 175+ additional MCP tools on top of Claude Code's native toolset. The relationship is:

```
Claude Code (executor, planner, native tools)
    │
    └── Ruflo MCP server (orchestration, memory, routing, swarm coordination)
            │
            ├── memory_search / memory_store  (HNSW vector DB, 150x faster retrieval)
            ├── swarm_init / agent_spawn       (coordinate Claude Code Task() calls)
            ├── hooks_route                    (intelligent routing with model recommendations)
            └── neural_train                   (SONA self-learning)
```

### Core Architecture

```
User → Ruflo (CLI/MCP) → Router → Swarm → Agents → Memory → LLM Providers
                       ↑                          ↓
                       └──── Learning Loop ←──────┘
```

**Layers:**
- **Entry:** CLI or MCP server
- **Routing:** Q-Learning Router, Mixture of Experts (8 experts), 42+ Skills, 17 Hooks
- **Swarm Coordination:** 4 topologies (hierarchical, mesh, ring, star), 5 consensus protocols (Raft, Byzantine, Gossip, CRDT, majority)
- **Agents:** 60+ typed agents (coder, tester, reviewer, architect, security, etc.)
- **Memory (RuVector):** HNSW index, SQLite/AgentDB, PostgreSQL with 77+ SQL functions, knowledge graph with PageRank

### Self-Learning System (ADR-049)

```
memory_search → Judge → Distill → Consolidate → Route
     ↑                                              │
     └──────────────────────────────────────────────┘
```

- **SONA:** Self-Optimizing Neural Architecture — adapts routing in <0.05ms
- **EWC++:** Elastic Weight Consolidation — prevents catastrophic forgetting of successful patterns
- **ReasoningBank:** Stores successful trajectories with RETRIEVE→JUDGE→DISTILL cycle
- **MemoryGraph:** PageRank + Jaccard similarity knowledge graph over memory entries
- **AgentMemoryScope:** 3-scope isolation — project/local/user — with cross-agent transfer

### 3-Tier Model Routing

| Tier | Handler | Latency | Cost |
|------|---------|---------|------|
| 1 | Agent Booster (WASM) | <1ms | $0 |
| 2 | Haiku/Sonnet | 500ms-2s | Low |
| 3 | Opus | 2-5s | High |

The hooks system outputs `[TASK_MODEL_RECOMMENDATION] Use model="haiku"` → Claude Code's Task() tool should be called with that model. Ruflo **advises** Task() parameters, it doesn't replace Task().

### MCP Installation

```bash
# Add to Claude Code as MCP server
claude mcp add ruflo -- npx -y ruflo@latest mcp start

# Verify
claude mcp list
```

Once installed, Claude Code gets access to all 175+ Ruflo tools alongside its native tools.

### Anti-Drift Swarm Configuration

```javascript
// Recommended for coding tasks
swarm_init({
  topology: "hierarchical",  // Single coordinator catches drift early
  maxAgents: 8,              // Smaller team = less coordination overhead
  strategy: "specialized"    // Clear roles reduce ambiguity
})
```

### Key Skills (137+)

Categories: V3 Core, AgentDB, Swarm, GitHub, SPARC, Flow Nexus, Dual-Mode. Notable:
- `$sparc:architect`, `$sparc:coder`, `$sparc:tester` — SPARC methodology agents
- `$swarm-orchestration` — full swarm control
- `$agentdb-vector-search` — semantic memory search
- `$dual-spawn` / `$dual-coordinate` — Claude Code + Codex hybrid mode

### Failure Modes & Limitations

- **Alpha status:** `npx ruflo@v3alpha` — not production stable. API can break between versions.
- **Full install is 340MB:** Core CLI is ~45MB (`--omit=optional`). The ML/embedding stack is heavy.
- **Learning loop overhead:** The self-learning features add latency. Not appropriate for real-time interactive tasks.
- **Swarm drift in mesh topology:** The README explicitly warns about mesh topology causing drift. Hierarchical is strongly recommended.
- **Byzantine consensus requires 2/3 majority:** If more than 1/3 of agents fail, consensus breaks.
- **Multiple LLM providers add auth complexity:** API keys for Anthropic, OpenAI, Gemini needed if using multi-provider routing.
- **`npx` cold start:** Fresh download is ~20s; cached is ~3s. Not suitable for fast short tasks.

### Ubuntu Install Notes

Node.js 20+ required. `npm install -g ruflo@alpha` works on Ubuntu. The WASM Agent Booster and ML embeddings (ONNX) have pre-built binaries — should work on x64 Linux without compilation. No Ubuntu-specific issues mentioned.

### License

MIT — free to use commercially.

---

## 3. The Claude Protocol

**Repo:** `AvivK5498/The-Claude-Protocol`  
**Package name:** `beads-orchestration` (npm)  
**License:** MIT  
**Dependencies:** Claude Code with hooks support, Node.js, Python 3, beads CLI (auto-installed)

### Core Concept

> "Enforcement-first orchestration for Claude Code. Every agent tracked. Every decision logged. Nothing gets lost."

The Claude Protocol adds a **structural enforcement layer** around Claude Code. The insight is that instructions ("remember to investigate before coding") fail; constraints ("physically block you from writing code without reading the source first") work.

### Architecture

```
┌─────────────────────────────────────────┐
│         ORCHESTRATOR (Co-Pilot)         │
│  Plans with you (Plan mode)            │
│  Investigates with Grep/Read/Glob       │
│  Delegates implementation via Task()    │
└──────────────────┬──────────────────────┘
                   │  Task() calls
       ┌───────────┼───────────┐
       ▼           ▼           ▼
  ┌─────────┐ ┌─────────┐ ┌─────────┐
  │ react-  │ │ python- │ │ nextjs- │
  │supervisor│ │supervisor│ │supervisor│
  └────┬────┘ └────┬────┘ └────┬────┘
       │           │           │
  .worktrees/  .worktrees/  .worktrees/
  bd-BD-001    bd-BD-002    bd-BD-003
```

**Three layers:**
1. **Orchestrator:** Plans, investigates, delegates. NEVER writes code. Has `CLAUDE.md` with constraints.
2. **Supervisors:** Auto-generated per tech stack (react, python, nextjs, etc.). Read bead context, implement in isolated worktrees, push PRs.
3. **Beads:** Git-native tickets (`.beads/issues.jsonl`). One bead = one unit of work = one worktree = one PR.

### The 13 Hooks

**PreToolUse (7 hooks) — blocks before bad actions:**
1. Block orchestrator from writing code on `main` branch
2. Prompt for quick-fix approval on feature branches (shows filename + change size)
3. Block `git commit --no-verify` — hooks always run
4. Allow memory file writes (whitelist)
5. Require beads for supervisor dispatch
6. Enforce worktree isolation
7. Block closing epics with open children; enforce sequential dependency dispatch

**PostToolUse (3 hooks) — auto-log after good actions:**
1. Auto-log dispatch prompts as bead comments
2. Capture knowledge base entries
3. Enforce concise supervisor responses

**SubagentStop (1 hook):** Verify worktree exists, code pushed, bead status updated.

**SessionStart (1 hook):** Surface task status, recent knowledge, cleanup suggestions.

**UserPromptSubmit (1 hook):** Prompt for clarification on ambiguous requests.

### Beads Integration

```bash
# Bead workflow
bd comment BD-001 "LEARNED: TaskGroup requires @Sendable closures"
.beads/memory/recall.sh "concurrency"  # Search knowledge base
```

- Beads = `.beads/issues.jsonl` — git-trackable task database
- Each bead gets a worktree: `.worktrees/bd-BD-001`
- Closed beads are immutable — bug fixes become new beads with `bd dep relate`
- Knowledge base: `.beads/memory/knowledge.jsonl` + `recall.sh`

### What Gets Installed

```
.claude/
├── agents/           # Supervisors auto-created for your tech stack
├── hooks/            # 13 workflow enforcement hooks
├── skills/           # subagents-discipline, react-best-practices
└── settings.json
CLAUDE.md             # Orchestrator instructions
.beads/               # Task database + knowledge base
.worktrees/           # Isolated worktrees per task (dynamic)
```

### Failure Modes & Limitations

- **Beads CLI requires Homebrew (`brew install steveyegge/beads/bd`):** On Ubuntu this means installing Homebrew first — non-trivial for production servers. Alternative: build from source (Go binary).
- **Hooks are project-level, not session-scoped:** If you have multiple projects, each needs its own `.claude/hooks/` setup.
- **No hook fine-tuning without editing files:** The 13 hooks are baked in; customizing them requires understanding the hook scripts.
- **`git commit --no-verify` blocked globally:** This could conflict with external tools (CI scripts, etc.) that intentionally skip hooks.
- **Worktree accumulation:** Every task creates a `.worktrees/bd-NNN` directory. Without cleanup discipline, this grows fast.
- **Supervisors are auto-generated but tech-stack-specific:** Works well for web apps (React, Python, Next.js); less clear for novel stacks.
- **Single-repo assumption:** The architecture assumes one orchestrator → one repo. Cross-repo coordination isn't addressed.

### Ubuntu Install Notes

```bash
# Homebrew needed for beads CLI
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install steveyegge/beads/bd

# Then install the protocol
npx skills add AvivK5498/The-Claude-Protocol
# OR
npm install -g beads-orchestration
```

Homebrew on Ubuntu (omen-claw) is doable but adds a non-standard dependency. The beads CLI is a Go binary — could potentially be installed from source without Homebrew.

---

## 4. Awesome Claude Code Subagents

**Repo:** `VoltAgent/awesome-claude-code-subagents`  
**Count:** 127+ subagent definitions  
**License:** MIT (with caveat: "we do not audit or guarantee security or correctness of any subagent")

### Install Options

```bash
# As Claude Code plugin (recommended)
claude plugin marketplace add VoltAgent/awesome-claude-code-subagents
claude plugin install voltagent-core-dev

# Manual
cp agents/*.md ~/.claude/agents/   # global
cp agents/*.md .claude/agents/     # project-specific

# Interactive installer
curl -sO https://raw.githubusercontent.com/.../install-agents.sh
./install-agents.sh

# Meta-agent installer (use Claude to install agents)
curl -s .../categories/09-meta-orchestration/agent-installer.md -o ~/.claude/agents/agent-installer.md
```

### Categories

| # | Category | Plugin | Notable Agents |
|---|----------|--------|----------------|
| 01 | Core Development | `voltagent-core-dev` | api-designer, backend-developer, frontend-developer, fullstack-developer |
| 02 | Language Specialists | `voltagent-lang` | python-pro, typescript-pro, golang-pro, react-specialist, nextjs-developer |
| 03 | Infrastructure | `voltagent-infra` | devops-engineer, kubernetes-specialist, terraform-engineer, cloud-architect |
| 04 | Quality & Security | `voltagent-qa-sec` | code-reviewer, security-auditor, penetration-tester, debugger |
| 05 | Data & AI | `voltagent-data-ai` | ai-engineer, llm-architect, data-engineer, postgres-pro |
| 06 | Developer Experience | `voltagent-dev-exp` | mcp-developer, git-workflow-manager, refactoring-specialist |
| 07 | Specialized Domains | `voltagent-domains` | fintech-engineer, blockchain-developer, payment-integration |
| 08 | Business & Product | `voltagent-biz` | product-manager, technical-writer, business-analyst, scrum-master |
| 09 | Meta & Orchestration | `voltagent-meta` | multi-agent-coordinator, workflow-orchestrator, task-distributor, agent-organizer |
| 10 | Research & Analysis | `voltagent-research` | research-analyst, competitive-analyst, trend-analyst |

### Subagent File Format

```yaml
---
name: subagent-name
description: When this agent should be invoked
tools: Read, Write, Edit, Bash, Glob, Grep
model: sonnet  # opus | sonnet | haiku | inherit
---

You are a [role]...

## Communication Protocol
Inter-agent communication specs...

## Development Workflow
Structured implementation phases...
```

### Model Routing Philosophy

| Model | When | Examples |
|-------|------|---------|
| `opus` | Deep reasoning — architecture, security audits, financial | security-auditor, architect-reviewer, fintech-engineer |
| `sonnet` | Everyday coding — write, debug, refactor | python-pro, backend-developer, devops-engineer |
| `haiku` | Quick tasks — docs, search, dependency checks | documentation-engineer, seo-specialist, build-engineer |
| `inherit` | Follow parent conversation model | flexible agents |

### Tool Assignment Philosophy

- **Read-only agents** (reviewers, auditors): `Read, Grep, Glob`
- **Research agents** (analysts): `Read, Grep, Glob, WebFetch, WebSearch`
- **Code writers** (developers): `Read, Write, Edit, Bash, Glob, Grep`
- **Documentation** (writers): `Read, Write, Edit, Glob, Grep, WebFetch, WebSearch`

**Minimal necessary permissions** — each agent gets only what it needs.

### Key Insight: The `description` Field is Critical

Claude Code uses the `description` field to decide WHEN to invoke a subagent. Writing "Use proactively after code changes" makes Claude auto-invoke without being asked. This is the primary control plane.

### Failure Modes & Limitations

- **No quality guarantee:** "We do not audit or guarantee security or correctness." Community-contributed agents may have poor system prompts.
- **Subagents cannot spawn subagents:** Native Claude Code limitation — no chains. Meta orchestration agents work around this by having the main agent invoke them sequentially.
- **`inherit` model can be expensive:** If a haiku-appropriate task uses `inherit` while main conversation is Opus, you're paying Opus rates.
- **Plugin marketplace is new:** The `claude plugin marketplace add` command was recently added; availability/stability unclear.
- **Context window per subagent:** Each invocation starts fresh. Long-running subagents don't remember previous conversations in the same project without the `memory:` field.

---

## 5. Beads Kanban UI

**Repo:** `AvivK5498/Beads-Kanban-UI`  
**License:** MIT  
**Stack:** Next.js (frontend) + Rust binary (backend server)  
**Port:** 3007 (frontend) / 3008 (backend)

### What It Is

A visual Kanban UI that reads the beads CLI data format (`.beads/issues.jsonl`) and renders it as a board. Tight integration with The Claude Protocol ecosystem.

### Key Features

| Feature | Details |
|---------|---------|
| **Multi-project dashboard** | Status donuts per project, all in one view |
| **Kanban columns** | Open → In Progress → In Review → Closed |
| **GitOps** | Create/merge PRs from UI; CI status on cards; auto-close on merge |
| **Epic management** | Progress bars, subtask views, dependency enforcement |
| **Memory panel** | Browse/edit `.beads/memory/knowledge.jsonl` |
| **Agents panel** | View/configure `.claude/agents/*.md` — switch models, toggle tools |
| **Real-time sync** | File watcher on `.beads/issues.jsonl`; no manual refresh needed |
| **PR refresh** | Every 30 seconds |

### GitOps Flow

```
Claude Protocol creates bead → supervisor creates worktree → implements in isolation
    → Beads Kanban UI shows card "In Progress" 
    → supervisor pushes branch → creates PR
    → Beads Kanban UI shows CI status, merge button
    → user clicks merge → bead auto-closes → worktree cleaned up
```

No terminal needed for the PR workflow once the bead is in review.

### Agents Panel

The agents panel is particularly interesting: it reads `.claude/agents/*.md` and lets you:
- See all agent definitions with model badges (haiku/sonnet/opus)
- Switch an agent's model via dropdown
- Toggle all-tools access
- Changes write directly to the agent's `.md` frontmatter

This creates a GUI for agent management — no YAML editing required.

### Install

```bash
# Easy install
npm install -g beads-kanban-ui
bead-kanban

# From source (needs Node.js 18+ + Rust)
git clone https://github.com/AvivK5498/beads-kanban-ui
cd beads-kanban-ui && npm install && npm run dev:full
```

### Failure Modes & Limitations

- **Requires beads CLI:** The entire UI is useless without `bd` (beads CLI). Same Homebrew dependency issue as The Claude Protocol.
- **File watcher granularity:** Watches `.beads/issues.jsonl` — any corruption of this file breaks the board.
- **PR status via GitHub API:** Needs GitHub auth configured (via git credentials or GitHub CLI). Rate limits apply.
- **Rust binary download on install (~15MB):** One-time postinstall download. Corporate proxies may block this.
- **macOS + Linux only:** README says "macOS and Linux." The Rust binary needs to be compiled/downloaded for the specific platform.
- **Tightly coupled to The Claude Protocol:** Less useful as a standalone tool without the beads+hooks workflow.

### Ubuntu Install Notes

Same Homebrew issue for the beads CLI. The npm install will download a pre-built Rust binary for Linux x64 — should work on Ubuntu with no compilation required.

---

## 6. Claude Code Native Subagents

**Source:** `https://code.claude.com/docs/en/sub-agents` (official Anthropic docs)

### What They Are

Subagents are Claude Code's first-class mechanism for delegating tasks to specialized Claude instances within a session. Each runs in its **own context window** with a custom system prompt, tool restrictions, and independent permissions.

### File Format

```yaml
---
name: subagent-name          # required, lowercase-with-hyphens
description: When to invoke  # required, CRITICAL for auto-delegation
tools: Read, Grep, Glob      # optional; inherits all if omitted
disallowedTools: Write, Edit # optional denylist
model: sonnet                # opus | sonnet | haiku | inherit (default: inherit)
permissionMode: default      # default | acceptEdits | dontAsk | bypassPermissions | plan
maxTurns: 10                 # max agentic turns before stop
skills:                      # inject skills at startup (not inherited from parent)
  - skill-name
mcpServers:                  # MCP servers available to this subagent
  - server-name
hooks:                       # hooks scoped ONLY to this subagent's lifecycle
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./validate.sh"
memory: user                 # user | project | local — enables cross-session memory
---

System prompt here...
```

### Storage Locations (Priority Order)

| Location | Scope | Priority |
|----------|-------|---------|
| `--agents` CLI flag | Current session only | 1 (highest) |
| `.claude/agents/` | Current project | 2 |
| `~/.claude/agents/` | All projects | 3 |
| Plugin `agents/` dir | Where plugin enabled | 4 |

### Built-in Subagents

| Agent | Model | Tools | Purpose |
|-------|-------|-------|---------|
| **Explore** | Haiku | Read-only | Codebase exploration, search |
| **Plan** | Inherits | Read-only | Research during plan mode |
| **General-purpose** | Inherits | All | Complex multi-step tasks |
| Bash | Inherits | Bash | Terminal commands in separate context |
| statusline-setup | Sonnet | — | /statusline config |
| Claude Code Guide | Haiku | — | Questions about Claude Code |

### Background vs Foreground

- **Foreground:** Blocks until complete. Permission prompts and questions pass through.
- **Background:** Run concurrently. Permissions pre-approved before launch. Auto-denies un-pre-approved. **MCP tools NOT available in background subagents.**

### Key Capability: Per-Subagent Hooks

This is critical: hooks defined in subagent frontmatter run **only while that specific subagent is active** and are cleaned up when it finishes. This allows:

```yaml
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./validate-readonly.sh"
  PostToolUse:
    - matcher: "Edit|Write"
      hooks:
        - type: command
          command: "./run-linter.sh"
```

Project-level `settings.json` can also define `SubagentStart` / `SubagentStop` hooks that fire when ANY subagent starts or stops.

### Persistent Memory

```yaml
memory: user  # ~/.claude/agent-memory/<name>/
```

When enabled:
- Subagent gets a persistent directory across conversations
- MEMORY.md is auto-injected into system prompt (first 200 lines)
- Read/Write/Edit automatically added to tools

### Subagent Limitations (Critical)

- **Cannot spawn subagents** — no nested delegation. Only agents running as main thread (`claude --agent`) can use Task().
- **Background subagents cannot use MCP tools**
- **No session resumption** — each invocation is fresh (unless using `memory:` field)
- **Skills not inherited from parent** — must be listed explicitly in frontmatter
- **Transcripts stored per-session** in `~/.claude/projects/{project}/{sessionId}/subagents/`
- **Auto-cleanup** after 30 days (configurable via `cleanupPeriodDays`)

---

## 7. Claude Code Agent Teams

**Source:** `https://code.claude.com/docs/en/agent-teams` (official Anthropic docs)  
**Status:** Experimental (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`)

### Core Difference vs Subagents

| | Subagents | Agent Teams |
|--|-----------|-------------|
| Communication | Report up to parent ONLY | **Message each other directly** |
| Context | Own window; results return to caller | Own window; **fully independent** |
| Coordination | Main agent manages everything | **Shared task list, self-coordinate** |
| Token cost | Lower (summaries) | Higher (each = full Claude instance) |
| Best for | Focused tasks, only result matters | Complex work needing discussion |

### Architecture

```
Team lead (your main session)
    │
    ├── Shared task list (~/.claude/tasks/{team-name}/)
    ├── Mailbox (messaging between teammates)
    │
    ├── Teammate 1 (own context window)
    ├── Teammate 2 (own context window)
    └── Teammate N (own context window)
```

**Team config:** `~/.claude/teams/{team-name}/config.json` (has members array with names + agent IDs)  
**Task list:** `~/.claude/tasks/{team-name}/` (file-locked to prevent race conditions)

### Display Modes

- **in-process:** All teammates in same terminal. Shift+Down to cycle. Works in any terminal.
- **split panes:** Each teammate in its own tmux/iTerm2 pane. Requires tmux or iTerm2.
- **auto (default):** Uses split panes if already in tmux, otherwise in-process.

### Enabling & Launch

```bash
# Enable globally (settings.json)
{"env": {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"}}

# Or per-session
CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 claude --dangerously-skip-permissions --teammate-mode in-process
```

From OpenClaw, this requires `exec pty:true` because of the interactive bypass permissions prompt.

### Quality Gates via Hooks

Two team-specific hooks:
- **TeammateIdle:** Runs when a teammate is about to go idle. Exit code 2 = keep working.
- **TaskCompleted:** Runs when a task is being marked complete. Exit code 2 = reject completion.

### Current Limitations (from official docs)

- **No session resumption** for in-process teammates — /resume and /rewind don't restore teammates
- **Task status lags** — teammates sometimes fail to mark tasks complete; blocks dependent tasks
- **Shutdown can be slow** — waits for current request to finish
- **One team per session** — clean up before starting new team
- **No nested teams** — teammates cannot spawn teams or subagents
- **Lead is fixed** — can't promote teammate to lead or transfer leadership
- **Permissions set at spawn** — all teammates start with lead's mode; can change after but not at spawn
- **Split panes don't work** in VS Code integrated terminal, Windows Terminal, or Ghostty

---

## 8. Current Jarvis/OpenClaw Setup

**Source:** `AGENTS.md`, `SOUL.md`, `brain/AGENT_TEAMS.md`, `brain/STANDARDS.md` (workspace files)

### What's Already There

**Identity & Role Model:**
- Jarvis = COO role — Rob delegates direction, Jarvis handles execution
- "Rob talks to you only. He never interacts with subagents directly."
- Fully autonomous on internal operations; pauses only for irreversible/external actions

**Model Routing (already sophisticated):**
| Alias | Model | Use |
|-------|-------|-----|
| `opus` | claude-opus-4-6 | Main agent: planning, orchestration, chat |
| `sonnet` | claude-sonnet-4-5 | Builder subagents: code gen, refactors |
| `haiku` | claude-haiku-4-5 | Lightweight fallback |
| `mini` | gpt-5.1-codex-mini | Build loops, log parsing, cron |
| `codex` | gpt-5.3-codex | Fallback coding model |

**Subagent Discipline (already enforced via SOUL.md/AGENTS.md):**
- One task, one scope per builder
- Builders report to Jarvis, never to Rob
- Quality gate before delivery (tests, no secrets, no hardcoded paths, clean git)
- Plan before spawning — never spawn in loops

**Agent Teams (already enabled):**
```json
{"env": {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"}}
```
Real-world use: Blofin pipeline redesign — 4 tasks, ~55 min total, teammates auto-coordinated on shared DB schema.

**Memory System:**
- `brain/status/status.json` — truth store, atomic writes
- `brain/memory/` — daily logs + long-term learnings
- `MEMORY.md` — curated cross-session memory (main session only)
- Daily notes: `memory/YYYY-MM-DD.md`

**Heartbeat:**
- Isolated Haiku cron every hour — health checks, status.json updates, ntfy alerts
- Does NOT wake main Jarvis session unless something is wrong

**Standards:**
- Change classification (Safe / Normal / Risky / Destructive)
- Explicit pre-delivery checklist
- Cross-AI adversarial review for major architecture decisions

**GitHub Workflow:**
- `robbyrobaz/ai-workshop` issues with label-based state machine
- `ai-task` → `in-progress` → unlabeled (human review) → closed

### What's Missing / Gaps

1. **No task board / Kanban:** Tasks live in status.json (flat list) and GitHub issues. No visual board, no dependency tracking between tasks.
2. **No git-native task tracking (Beads):** Tasks aren't tracked in the repo. If a session dies mid-task, recovery relies on human memory + status.json.
3. **No enforcement hooks:** Jarvis's constraints are in SOUL.md (instructions), not hooks (enforcement). A sufficiently confused session could still violate rules.
4. **No persistent subagent memory:** Builders start fresh each time. No pattern accumulation — the same codebase research gets redone session after session.
5. **No structured knowledge base:** Learnings go to `brain/memory/` as markdown but aren't semantically searchable (no HNSW/vector search).
6. **No worktree isolation for builder tasks:** Builders can accidentally touch main or conflict with each other if tasks overlap.
7. **No dependency tracking between tasks:** status.json doesn't enforce "task B waits for task A."
8. **OpenClaw subagents ≠ Claude Code subagents:** OpenClaw's `sessions_spawn` mechanism is different from Claude Code's native `.claude/agents/` subagent system. Currently mixing two systems.

---

## 9. Specific Questions Answered

### Q1: Does Dynamic Kanban MCP support multi-agent card updates simultaneously, or does one agent lock the board?

**Answer: NOT explicitly supported for multi-agent concurrent writes.**

The README describes "thread-safe atomic operations" and "data integrity with backup/restore," but this protects against file corruption during single-writer scenarios. The mode system (Autonomous/Manual) prevents **human vs. AI** conflicts by queuing AI actions during Manual mode.

For **AI vs. AI** (multiple Claude agents simultaneously calling `kanban_move_card`), there is no mention of distributed locks, optimistic concurrency, or agent-specific lanes. Since state persists to a single JSON file, simultaneous writes could corrupt or silently overwrite each other.

**Practical implication:** Dynamic Kanban MCP is safe for a single orchestrating Claude agent with one human watching. It is NOT safe for a multi-agent swarm where 3 builder agents try to update their card status simultaneously.

**Workaround if needed:** Route all kanban updates through the orchestrating agent (one writer), never let builders update the board directly.

---

### Q2: Does Claude-Flow's Ruflo MCP work with Claude Code's native Task() tool or does it replace it?

**Answer: Complementary — works WITH Task(), does not replace it.**

Ruflo is an MCP server that adds 175+ tools to Claude Code's toolset. Claude Code's native Task() tool (which spawns subagents) still exists and operates normally. The relationship:

- Ruflo's hooks system outputs `[TASK_MODEL_RECOMMENDATION] Use model="haiku" → Pass model="haiku" to Task tool for cost savings` — the hooks **advise on Task() parameters**, meaning Ruflo treats Task() as the executor.
- Ruflo's `swarm_init` and `agent_spawn` are coordination-layer tools — they orchestrate how and when to use Task() (and by extension, how many agent contexts to create).
- The SONA/learning system tracks patterns from Task() outcomes and feeds back routing decisions.

**In short:** Ruflo is the brain + memory layer. Task() is the legs. You can use Ruflo's 175 tools to plan and coordinate work, then execute via native Task(). Or you can use Ruflo's `agent_spawn` directly, but that's a higher-level wrapper over the same underlying mechanism.

**Practical implication:** Adding Ruflo to a Claude Code setup doesn't break existing Task()-based workflows. It augments them with memory, routing intelligence, and swarm coordination.

---

### Q3: What's the difference between Claude Code agent teams vs subagents for a COO→specialist pattern?

**Answer: Subagents is the right primitive. Agent Teams are for when specialists need to talk to each other.**

| Criterion | Subagents | Agent Teams |
|-----------|-----------|-------------|
| COO stays as single interface to Rob | ✅ COO (main session) receives all reports | ✅ COO (lead) coordinates team |
| Specialists work independently | ✅ Each in own context | ✅ Each in own context |
| Cross-specialist communication | ❌ Only through COO | ✅ Direct messaging |
| Token cost | ✅ Lower (summaries returned) | ⚠️ Higher (full contexts) |
| Setup complexity | ✅ Simple `.claude/agents/` files | ⚠️ PTY + interactive launch, experimental |
| Session resumption | ✅ Via `memory:` field | ❌ Not supported for in-process |
| MCP tools available | ✅ Yes (not in background) | ✅ Yes |
| Specialist count | Flexible | Flexible |

**For the Jarvis COO pattern (Rob→Jarvis→Specialists→Results):**

- **Use subagents** when: specialists can be fully defined before dispatch, they operate independently, and results just need to be delivered to COO. This matches 90% of Jarvis's current use cases (code gen, refactors, monitoring, deployments).
- **Use agent teams** when: you have 3+ specialists who need to discover each other's progress during execution (e.g., a frontend builder needs to know what API the backend builder just shipped). The auto-coordination saves Jarvis from having to intermediary every message.

**Current Jarvis recommendation:** Subagents for isolated tasks, agent teams for complex refactors where inter-agent coordination matters. This matches what's already in `brain/AGENT_TEAMS.md`.

---

### Q4: Can The Claude Protocol's hooks be scoped per-agent, or do they apply globally?

**Answer: The Claude Protocol's 13 hooks are project-level (global). However, Claude Code's native hook system supports per-subagent hooks.**

**The Claude Protocol's approach:** Hooks live in `.claude/hooks/` and `settings.json`. They apply to the entire Claude Code session — both the orchestrator and supervisors. The hooks are designed this way intentionally: the orchestrator-specific constraints (can't write code on main) work because the hooks check the calling context (branch name, who invoked the tool) rather than scoping to a specific agent identity.

**Native Claude Code approach:** You CAN scope hooks per-agent via subagent frontmatter:

```yaml
---
name: db-reader
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./validate-readonly.sh"
---
```

These hooks run **only while that specific subagent is active** and are cleaned up when it finishes. Project-level `settings.json` hooks can also match by agent type via `SubagentStart` matchers.

**Practical implication:** The Claude Protocol uses global hooks cleverly (they check context, not identity) and this works well for a single-project orchestrator pattern. If you want agent-type-specific enforcement (e.g., "the security-auditor subagent can never use Write"), the native frontmatter hook system is the right primitive.

---

### Q5: Known failure modes and limitations in current versions

**Dynamic Kanban MCP:**
- No multi-agent concurrent write support
- State in a single local JSON file — no durability if process crashes mid-write
- No authentication on WebSocket
- "Production-ready" claim unverified (no tests mentioned)
- Mode switching requires user action

**Ruflo/Claude-Flow:**
- v3alpha — API unstable, breaking changes expected
- 340MB full install; WASM + ML/ONNX dependencies
- Anti-drift requires explicit hierarchical topology configuration
- Byzantine consensus breaks if >1/3 agents fail simultaneously
- Self-learning adds latency not suitable for real-time interactive use
- Multiple LLM provider keys needed for full functionality

**The Claude Protocol:**
- Beads CLI requires Homebrew (non-trivial on production Ubuntu servers)
- Hooks are project-level; per-project setup required
- `git commit --no-verify` blocked globally (can conflict with external tooling)
- Worktree accumulation without cleanup discipline
- Single-repo assumption; cross-repo coordination unsupported

**Awesome Claude Code Subagents:**
- No security audit on contributed agents — review before use
- Subagents cannot spawn subagents (Claude Code limitation)
- Plugin marketplace command (`claude plugin marketplace add`) is new and may be unstable
- `inherit` model can be expensive if main session is Opus

**Beads Kanban UI:**
- Requires Homebrew (beads CLI dependency)
- GitHub API rate limits for PR status
- Tightly coupled to The Claude Protocol — low value as standalone
- Rust binary download may fail behind corporate proxies

**Claude Code Subagents:**
- Cannot spawn subagents (no chains)
- Background subagents cannot use MCP tools
- No nested delegation
- Task status lags (can block dependent tasks)

**Claude Code Agent Teams:**
- Experimental — `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- No session resumption for in-process teammates
- No nested teams, no leadership transfer
- Permissions set at spawn, not per-teammate
- Lead can start working instead of delegating (training issue)
- Split panes require tmux (additional install)

---

### Q6: Licensing, auth, or Ubuntu-specific install issues

| Tool | License | Auth Issues | Ubuntu Issues |
|------|---------|-------------|---------------|
| Dynamic Kanban MCP | Not stated (likely MIT) | None — runs locally | None — pure Python |
| Ruflo/Claude-Flow | MIT | ANTHROPIC_API_KEY required; optional: OpenAI, Google API keys | Node.js 20+ required; ONNX binaries are pre-built for x64 Linux |
| The Claude Protocol | MIT | None for core; GitHub auth needed for PRs | **Homebrew required** for beads CLI — `brew install steveyegge/beads/bd` |
| Awesome Subagents | MIT | None | None — markdown files |
| Beads Kanban UI | MIT | GitHub auth for GitOps features | **Homebrew required** for beads; Rust binary pre-built for Linux x64 |
| Claude Code Subagents | N/A (Anthropic platform) | Inherits Claude Code auth | None |
| Claude Code Agent Teams | N/A (Anthropic platform) | Inherits Claude Code auth | tmux required for split-pane mode |

**Critical flag:** Both The Claude Protocol and Beads Kanban UI require `brew install steveyegge/beads/bd`. On omen-claw (Ubuntu production server), this means installing Homebrew first or finding an alternative beads installation method. The beads CLI is a Go binary — it should be possible to build from source (`go install github.com/steveyegge/beads@latest`) if the Go binary exists. **This is the #1 Ubuntu install issue across the stack.**

---

### Q7: How does the current Jarvis/OpenClaw setup compare?

**What Jarvis already does well (matching or exceeding these tools):**

✅ **COO→Specialist delegation pattern** — Core of SOUL.md. Already enforced via prompt engineering.  
✅ **Multi-model routing** — opus/sonnet/haiku/mini/codex with explicit escalation chain. More sophisticated than most tools (Ruflo's 3-tier is similar but less model variety).  
✅ **Status truth store** — `brain/status/status.json` — atomic writes, session-agnostic.  
✅ **Memory continuity** — Daily notes + MEMORY.md + brain/memory/ — more structured than most setups.  
✅ **Agent Teams** — Already enabled and used (Blofin pipeline redesign). Real production lessons documented.  
✅ **Heartbeat monitoring** — Isolated Haiku cron, ntfy alerts — more operationally mature than any of these tools provide out of the box.  
✅ **Cross-AI adversarial review** — Manual but exists. The Claude Protocol doesn't have this.  
✅ **GitHub issue workflow** — Structured label-based state machine.

**What Jarvis is missing that these tools offer:**

❌ **Enforcement hooks** — SOUL.md says "don't do X" but nothing physically blocks it. The Claude Protocol's hooks would add hard enforcement.  
❌ **Task visualization / Kanban** — status.json is machine-readable but not human-visual. Dynamic Kanban MCP or Beads Kanban UI would provide this.  
❌ **Git-native task tracking** — Tasks aren't in the repo. Session interruption means context loss. Beads would fix this.  
❌ **Worktree isolation for builders** — Builder subagents currently operate on the same working tree as the main session. Risk of conflicts.  
❌ **Persistent subagent memory** — Builders start fresh. Claude Code's native `memory:` frontmatter field + Ruflo's HNSW memory would let builders accumulate knowledge about the codebase.  
❌ **Semantic knowledge search** — `brain/memory/` is grep-searchable at best. Ruflo's HNSW + ReasoningBank would make this semantically searchable.  
❌ **Task dependency enforcement** — No mechanism prevents builder B from starting before builder A finishes a prerequisite.  
❌ **Subagent definitions as files** — Currently builders are spawned ad-hoc with inline prompts. Moving to `.claude/agents/*.md` would enable versioning, reuse, and tool restriction.

---

## 10. Synthesis: How They Work Together

These tools form three distinct layers of the same stack:

```
┌─────────────────────────────────────────────────────────┐
│  TASK TRACKING LAYER                                    │
│  Beads (git-native tasks) + Beads Kanban UI (visual)    │
│  OR: Dynamic Kanban MCP (simpler, AI-controlled)        │
└─────────────────────────────────────────────────────────┘
                         │
┌─────────────────────────────────────────────────────────┐
│  ORCHESTRATION / ENFORCEMENT LAYER                      │
│  The Claude Protocol (hooks + worktrees + structure)    │
│  OR: Ruflo (self-learning + swarm coordination)         │
│  + Awesome Subagents (pre-built specialist definitions)  │
└─────────────────────────────────────────────────────────┘
                         │
┌─────────────────────────────────────────────────────────┐
│  EXECUTION LAYER                                        │
│  Claude Code Native Subagents (.claude/agents/)         │
│  OR: Claude Code Agent Teams (EXPERIMENTAL)             │
└─────────────────────────────────────────────────────────┘
```

**The Claude Protocol + Beads + Beads Kanban UI** form one coherent stack (same author: AvivK5498). They solve the enforcement + tracking problem together. The downside is the Homebrew/beads CLI dependency.

**Ruflo** solves a different problem: it adds **intelligence and memory** to an existing Claude Code setup. It doesn't replace the task tracking layer but augments the orchestration layer with self-learning routing.

**Dynamic Kanban MCP** is the lightest option for task visualization — pure Python, MCP-native, no external dependencies. Good for a single orchestrating agent scenario but not multi-agent.

**Awesome Claude Code Subagents** is an instant library of specialist definitions. Drop them into `.claude/agents/` and get 127 specialists immediately. Complements any orchestration layer.

### Combining with Jarvis

The highest-value additions to the current Jarvis setup, in priority order:

1. **Claude Code native subagent files** (`.claude/agents/`) — formalize current ad-hoc builder spawning into versioned, reusable definitions with proper tool restrictions. Zero new dependencies.

2. **The Claude Protocol's hook system** (selectively) — adopt the 13 enforcement hooks without necessarily adopting beads. The hook scripts can be copied and adapted. This adds real enforcement without relying on prompt instructions.

3. **Dynamic Kanban MCP** — for single-agent task visualization during complex projects. Lightweight, Python-only. The COO (Jarvis) updates the board; builders don't touch it directly.

4. **Ruflo's memory system** — specifically `memory_store`/`memory_search` + persistent subagent memory via `memory: project` frontmatter. Eliminates repeated codebase investigation. Can be added without the full Ruflo stack.

5. **Beads** (lower priority) — solves session-persistence of tasks better than any other option, but the Homebrew dependency on Ubuntu is a real friction point. Evaluate after #1-4.

---

## 11. Recommendation Matrix

| Need | Best Tool | Alternative |
|------|-----------|-------------|
| Specialist definitions | Awesome Claude Code Subagents | Custom `.claude/agents/` files |
| Enforcement (hard blocks) | The Claude Protocol hooks | Custom hooks in `.claude/hooks/` |
| Task visualization | Dynamic Kanban MCP | Beads + Beads Kanban UI |
| Session-persistent tasks | Beads | GitHub Issues (current) |
| Multi-specialist coordination (same repo) | Claude Code Agent Teams | OpenClaw subagents + manual |
| Self-learning routing | Ruflo v3 memory + SONA | Manual model selection (current) |
| Cross-session subagent memory | Native `memory: project` field | `brain/memory/` markdown (current) |
| Worktree isolation | The Claude Protocol | Manual `git worktree` |
| GitOps from browser | Beads Kanban UI | GitHub web UI (current) |

---

*Research complete. Next phase: design the target architecture using these primitives.*

# Agent Stack — Final Executive Summary
**Phase 4 of 4**  
**Date:** 2026-02-19  
**Status:** Ready for Rob's decision

---

## What We're Building

A structured upgrade to the Jarvis setup that formalizes what's already working into versioned, enforceable files. Instead of ad-hoc subagents spawned with inline prompts and constraints that live only in SOUL.md, you get named specialist agents with explicit tool permissions, a QA layer with a real identity, and bash guards that physically block the bad calls — not just ask nicely. The goal is simple: less "I hope Jarvis doesn't do something dumb" and more "the system won't let it."

---

## The Stack

| Tool | Purpose | Install Command | Status |
|------|---------|-----------------|--------|
| Claude Code native agents (`.claude/agents/`) | Versioned specialist definitions with tool restrictions and model pinning | No install — just `.md` files | **Proven / Do now** |
| Claude Code hooks (`.claude/hooks/`) | Physical enforcement — blocks destructive bash, scans for secrets after writes | No install — bash scripts, `chmod +x` | **Proven / Do now (but fix the implementation — see Critic section)** |
| `brain/status/status.json` | Session health, heartbeat state — KEEP as-is | Already in place | **Proven / Keep unchanged** |
| GitHub Issues (ai-workshop) | External project tracking — KEEP as-is | Already in place | **Proven / Keep unchanged** |
| Agent Teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) | Complex parallel refactors where specialists need to talk to each other | Already enabled | **Experimental / Keep, use sparingly** |
| Dynamic Kanban MCP (`renatokuipers/dynamic-kanban-mcp`) | Visual task board + dependency tracking | `pip3 install websockets pydantic` + clone | **Deferred — adds infra complexity before core is solid** |
| Ruflo v3alpha | Vector memory for subagents, self-learning routing | `npm install -g ruflo@alpha` | **Deferred — v3alpha is genuinely unstable, 340MB, solves a problem you don't have yet** |
| Beads CLI / Beads Kanban UI | Git-native tasks, nicer visual board | Requires Homebrew on Ubuntu | **Deferred — Homebrew on omen-claw is a non-starter for now** |

**Dropped from PRD:** `python-pro` persona (too much overlap with ml-engineer for current projects), the "continuous task pump" (dangerous for active ML runs), hard QA gate on the kanban (premature), `coo.md` as a standalone subagent file (architecturally broken — see Critic section).

---

## Your Agent Team

**crypto-researcher** (Sonnet): Your market intelligence layer. Give it a research question about a trading signal, token, on-chain metric, or strategy — it searches the web, synthesizes findings, and returns a structured report with specific data points and a "TRADING SYSTEM IMPACT" flag when findings should change your setup. It cannot write code, run scripts, or touch files. Read-only plus web access.

**ml-engineer** (Sonnet): Python and quant work — backtesting, data pipelines, signal analysis code, Numerai model work, anything in the Blofin stack's Python layer. Full code access (Read, Write, Edit, Bash, Grep, Glob) with a post-write hook that runs ruff and scans for hardcoded secrets. It does NOT touch infrastructure (systemd, nginx) or frontend (Flask templates, charts).

**dashboard-builder** (Sonnet): Everything visual — Flask templates, Chart.js and Plotly charts, the Blofin dashboard at port 8888, HTML/CSS, UI additions to reporting pages. Same full code access as ml-engineer but scoped to frontend work. Will not touch Python business logic or database schema. Runs a post-write hook that validates HTML syntax.

**devops-engineer** (Sonnet): The omen-claw operations specialist. Systemd units, nginx configs, cron jobs, service restarts, disk and log management, dependency installs. Backs up configs before touching them, validates syntax before applying (`systemd-analyze verify`, `nginx -t`), and logs every service it restarts. Has the most risky tool access and the most enforcement around it.

**qa-sentinel** (Opus): The gatekeeper. Runs after every specialist completes work before anything reaches Rob. Read-only — it can read files, run `git diff`, run pytest, but cannot modify anything. Issues a clear APPROVED or REJECTED verdict with specific findings. Uses Opus because this is where you want reasoning quality, not speed. A QA Sentinel that misses a hardcoded API key costs you more than the Opus rate differential.

---

## How a Task Flows

**Scenario:** Rob asks Jarvis — "Can you research whether Bollinger Band squeeze signals improve NQ win rate on the 5m chart? And if it looks promising, build a quick backtest."

**Step 1 — Jarvis receives and breaks it down**  
One sentence acknowledgment. Internally: this is two tasks. Task A: research (crypto-researcher). Task B: backtest implementation, contingent on Task A findings (ml-engineer, only if research supports it). Jarvis updates `brain/status/status.json` with both tasks.

**Step 2 — crypto-researcher runs the research**  
Jarvis spawns crypto-researcher with a specific brief: *"Research Bollinger Band squeeze signals applied to NQ (Nasdaq futures) on the 5-minute chart. Find: (1) what the signal is and how it's typically defined, (2) any published win-rate data, (3) relevant discussion from trading communities, (4) any concerns about this signal on short timeframes. Check workspace files first for any existing BB work. Output a structured research report."*

crypto-researcher searches the web, reads any existing workspace research, and returns a report with findings, sources, data points, and — if it finds conflicting evidence on short-timeframe reliability — a `⚠️ TRADING SYSTEM IMPACT:` flag.

**Step 3 — QA reviews the research report**  
Jarvis routes the report to qa-sentinel: *"Review this research report for Card [ID]. Check: are claims sourced, are limitations stated, are recommendations actionable?"* qa-sentinel reads the report, runs a quick check against STANDARDS.md, and returns APPROVED with any caveats.

**Step 4 — Jarvis decides on the backtest**  
If research returned strong signal data, Jarvis proceeds. If the research flagged serious concerns (e.g., BB squeeze has poor statistical basis on 5m timeframes), Jarvis delivers only the research to Rob with a clear recommendation: *"Research doesn't support this — here's why. Want me to look at a different timeframe or signal?"*

Assuming proceed: Jarvis spawns ml-engineer with a precise brief including the research report's findings, the signal definition, and what output is expected — *"Working on Card [ID]. Build a backtest using the BB squeeze definition from the attached research (20-period BB, 2SD, Keltner Channel 20/1.5). NQ 5m data, last 90 days if available. Report win rate, expectancy, max drawdown. Do not optimize parameters — we want raw signal stats, not curve-fit results. Use the existing backtest framework in /path/to/blofin-stack if one exists."*

**Step 5 — ml-engineer builds the backtest**  
Explores the existing codebase first (always). Writes the backtest script. Runs it. The post-write hook scans for secrets and lints the file. ml-engineer returns a completion report: what was done, files modified, test/run results, and notes for QA.

**Step 6 — QA reviews the code**  
qa-sentinel gets the completion report plus the modified files. Checks: Does the code match the brief? Any hardcoded values that should be config? Did it touch files outside scope? Are results plausible or is something clearly wrong? Returns APPROVED or REJECTED with specifics.

**Step 7 — Jarvis delivers to Rob**  
One clean message: *"BB squeeze research done and backtest built. Short version: [win rate], [expectancy], [key finding]. Full research report attached. Backtest code is in [path]. One thing to know: [anything QA flagged that's worth Rob seeing]. Want me to extend this or test on a different timeframe?"*

Total agent hops: 4 (crypto-researcher → qa-sentinel → ml-engineer → qa-sentinel). Rob sees none of it until Step 7. No scaffolding, no status pings during execution, just the result.

---

## What the Critic Found

**Issue 1 — The hook scripts are completely broken. (Critical)**  
Every hook script in the PRD uses `CLAUDE_TOOL_ARGS` and `CLAUDE_TOOL_RESULT_PATH` as environment variables. These don't exist. Claude Code delivers hook context via stdin as JSON. Every hook will silently receive an empty string, match nothing, and exit 0. You'd believe you have guards; you wouldn't. Fix: read from stdin, parse with Python one-liner. Verify against the current Claude Code version before writing a single hook.

**What to do:** Before writing any hook, run a smoke test — a 5-line hook that appends `$(cat)` to a log file, wire it to PreToolUse on Bash, and confirm the JSON shows up. If it doesn't, the hook system is not wired up correctly and nothing else matters.

---

**Issue 2 — `coo.md` as a subagent doesn't make sense. (Critical)**  
The PRD defines Jarvis (the COO) as a `.claude/agents/` subagent file with `disallowedTools: Write, Edit`. But Jarvis IS the main session — there's no parent above him to invoke `coo.md`. That `disallowedTools` restriction only applies when something runs the COO *as a subagent*, which never happens. The core enforcement premise for the COO is a no-op.

**What to do:** Ditch `coo.md` as an agent file. The right place for COO-level constraints is a global `PreToolUse` hook in `settings.json` — one that fires on every session regardless of which agent is active. SOUL.md and AGENTS.md stay as the source of truth for identity. Don't duplicate them into agent files.

---

**Issue 3 — MCP server inheritance is backwards from what the PRD assumes. (Critical)**  
The PRD says specialists won't have `dynamic-kanban` in their `mcpServers:` field, so they won't be able to touch the kanban — enforcing the single-writer rule. But omitting the field likely means *inherit all MCP servers from parent*, not *get none*. If `dynamic-kanban` is registered in the main session's MCP config, specialists will likely inherit it. The entire single-writer enforcement mechanism may be inverted.

**What to do:** Test it. Spin up a test subagent, check whether `kanban_status()` is available inside it. If inheritance is the default, the enforcement requires explicitly setting `mcpServers: []` in every specialist frontmatter — or blocking at the MCP call level via hooks. This needs a real answer before the kanban goes live, which is another reason to defer it.

---

**Issue 4 — `~/.claude/mcp.json` is probably the wrong path. (Critical)**  
This path isn't standard Claude Code. MCP registration goes through `claude mcp add` (which writes to `~/.claude/claude_desktop_config.json`) or project-level `.claude/settings.json`. Write to the wrong path and the kanban server silently never loads.

**What to do:** Run `claude mcp list` on omen-claw, see where registered servers are stored, and use that path. This is a 2-minute check that saves a debugging session.

---

## What to Decide

- **Is the hook stdin API actually what's described?** (Highest impact — the entire enforcement layer depends on this.) Verify with a smoke test before writing any guard script. If the API has changed in the current Claude Code version, the entire hooks section of the PRD needs rewriting.

- **Do you want the kanban at all?** The critic's honest assessment: you probably won't watch a browser tab kanban regularly, and `status.json` already handles the machine-readable side. The kanban adds a pretty board and dependency tracking. Is that worth a persistent Python process on omen-claw and 3 critical issues to resolve around its MCP integration? Defer until the agent files + hooks are proven and you're actually feeling the pain of not having a visual board.

- **QA Sentinel on all outputs, or code-only?** Using Opus for qa-sentinel on a daily market research report triples the cost of that report. The recommendation: mandatory for anything that modifies files, COO judgment for research-only outputs. But this is your call — do you want hard rules or judgment calls?

- **Is devops-engineer allowed passwordless sudo for systemctl/nginx?** It needs it to actually restart services, not just write config files. Tight allowlist (`NOPASSWD: /bin/systemctl, /usr/sbin/nginx` only) is low additional risk given the existing setup, but you should explicitly decide this rather than let it be implicit.

- **Where do agents get secrets legitimately?** crypto-researcher may need price API keys. ml-engineer needs Numerai credentials. The hooks scan for hardcoded secrets, but nothing defines how agents get credentials they actually need. Establish the pattern now: env vars injected via agent frontmatter `env:` field, or read from a config file path that's in `.gitignore`. Pick one.

- **Should the heartbeat monitor for stuck tasks?** If ml-engineer maxes out at `maxTurns: 40` or hits a context limit, the task just stops with no completion report. The kanban card (when added) would stay stuck in "Delegated." A simple heartbeat check — "has any card been in Delegated for >2 hours?" — via reading `brain/kanban/kanban-progress.json` directly would catch this. Worth adding to the heartbeat when kanban goes live.

---

## Recommended Next Step

Verify the Claude Code hook stdin API with a smoke test on omen-claw — 10 lines of bash, one `PreToolUse` trigger, confirm the JSON payload arrives — then write the agent `.md` files.

---

*Generated by Jarvis subagent, Phase 4. Sources: 01-research.md, 02-PRD-draft.md, 03-AI-review.md, AGENTS.md, SOUL.md.*

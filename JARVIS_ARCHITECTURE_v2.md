# Jarvis Architecture v2 — Design Document

**Author:** Rob Hartwig + Claude Opus 4.6
**Date:** 2026-02-16
**Status:** FINAL — Cross-reviewed (Claude vs Claude-adversarial, 2 rounds)
**Review:** OpenAI Codex unavailable (quota exhausted). Used adversarial Claude agent instead. See appendix for full review.

---

## 1. Problem Statement

The current OpenClaw setup on omen-claw (HP Omen server) has grown organically into a tangled mess:
- Repos are intertwined (2nd-brain acting as parent for all code projects)
- No clear agent personas or boundaries — one main agent does everything
- When OpenClaw breaks (rate limits, gateway crash), the user loses all AI assistance
- No visibility into what agents are doing without manually checking
- GitHub Issues/PRs workflow requires context-switching and babysitting
- Development artifacts (status reports, temp files) accumulate everywhere
- No quality gate — agents take shortcuts with no review before delivery

### What works today
- Blofin trading pipeline (running, profitable signal detection)
- Server ops automation (backups, health checks, data retention)
- OpenClaw gateway with Telegram + WebChat channels
- Model routing with fallback chain (opus → sonnet → haiku)

### What needs to change
- Single point of failure (OpenClaw gateway down = no AI assistant)
- No persistent agent personas with specialized knowledge
- No automated quality review before work is delivered
- No real-time visibility into agent activity
- Messy repo structure with no graduation path for projects

---

## 2. Design Goals

1. **Single conversation interface** — Rob talks to Jarvis only. Jarvis handles everything downstream.
2. **Resilient** — Jarvis is reachable even when OpenClaw is broken (via Claude Code CLI fallback).
3. **Visible** — Rob can see what's happening at any time without asking.
4. **Quality-gated** — No work is delivered without review.
5. **Scalable** — Support multiple projects per week with AI automation.
6. **Clean** — Each project in its own repo, clear boundaries, no artifact accumulation.

---

## 3. Architecture Overview

```
                    ┌──────────┐
                    │   Rob    │
                    │  (CEO)   │
                    └────┬─────┘
                         │
            ┌────────────┼────────────┐
            │            │            │
      ┌─────▼─────┐ ┌───▼────┐ ┌────▼─────┐
      │ Telegram   │ │WebChat │ │Claude CLI│
      │ (primary)  │ │(backup)│ │(fallback)│
      └─────┬──────┘ └───┬────┘ └────┬─────┘
            │            │            │
            └────────────┼────────────┘
                         │
                  ┌──────▼──────┐
                  │   JARVIS    │
                  │   (COO)     │
                  │             │
                  │ Brain: ~/.jarvis/
                  │ SOUL.md, memory,
                  │ STATUS.md   │
                  └──────┬──────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
    ┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼─────┐
    │  ARCHITECT │ │   OPS     │ │ BUILDERS  │
    │  (CTO)     │ │  Agent    │ │ (pool)    │
    │            │ │           │ │           │
    │ Code review│ │ Health    │ │ Claude    │
    │ Graduation │ │ Backups   │ │ Agent     │
    │ Standards  │ │ Monitoring│ │ Teams     │
    └───────────┘ └───────────┘ └───────────┘
```

---

## 4. Jarvis Brain — Filesystem Layout

Jarvis's brain lives on the filesystem, independent of OpenClaw's runtime.
Both OpenClaw and Claude Code CLI can read the same files.

```
~/.jarvis/
├── SOUL.md                  # Jarvis persona, rules, behavior
├── STATUS.md                # Live status board (updated by agents)
├── ROSTER.md                # Agent registry — who does what
├── PLAYBOOK.md              # Standard procedures for common tasks
├── memory/
│   ├── long-term.md         # Persistent learnings, decisions
│   ├── projects.md          # Active project index
│   └── daily/
│       └── 2026-02-17.md    # Daily log
├── agents/
│   ├── architect/
│   │   └── SOUL.md          # CTO persona
│   ├── ops/
│   │   └── SOUL.md          # Ops persona
│   └── builder-template/
│       └── SOUL.md          # Template for project builders
└── watchdog/
    └── health-check.sh      # Independent OpenClaw health monitor
```

---

## 5. Agent Personas

### 5.1 Jarvis (COO / Personal Assistant)

**Model:** Opus (for nuanced understanding of Rob's intent)
**Channels:** Telegram (primary), WebChat, Claude CLI (fallback)
**Standing responsibilities:**
- Receive all requests from Rob
- Break down tasks, delegate to appropriate agents
- Review all work before delivering to Rob
- Maintain STATUS.md with real-time updates
- Daily briefing (morning summary of overnight activity)
- Ask clarifying questions when requests are ambiguous

**Key SOUL.md rules:**
- You are Rob's COO. He talks to you, not to other agents directly.
- NEVER deliver work without reviewing it first. Run tests. Read the code.
- When delegating, write specific instructions — not vague directives.
- Update STATUS.md before starting any task and after completing it.
- If OpenClaw is having issues, tell Rob immediately and suggest Claude CLI.
- Keep responses concise. Rob wants results, not essays.

### 5.2 Architect (CTO)

**Model:** Sonnet (fast, good at code), escalates to Opus for architecture decisions
**Triggered by:** Jarvis delegates code architecture, reviews, graduation decisions
**Standing responsibilities:**
- Review all code before it's committed to main branches
- Decide when a project graduates from ai-workshop to its own repo
- Maintain coding standards (no hardcoded paths, no secrets, proper .gitignore)
- Design system architecture for new projects

**Key SOUL.md rules:**
- You are the CTO. Quality over speed, always.
- Reject work that has: hardcoded secrets, missing tests, no README, temp files committed.
- When graduating a project, ensure: own repo, clean .gitignore, .env.example, README, CI-ready.
- You deploy Claude Agent Teams for parallel coding tasks.

### 5.3 Ops Agent

**Model:** Haiku (isolated cron job) for routine checks. Alerts Jarvis (Opus) only for incidents.
**Triggered by:** Scheduled cron jobs (hourly heartbeat)
**Standing responsibilities:**
- Server health checks (temps, disk, CPU, memory)
- Monitor OpenClaw gateway health
- Backup verification
- Incident response and documentation
- Data retention enforcement

**Key SOUL.md rules:**
- You manage omen-claw server. Stability is the top priority.
- Run health checks every 30 minutes via systemd timer.
- If CPU > 85°C or any service is down, alert Jarvis immediately.
- Document every incident in incidents.md.
- Never change system config without validating syntax first.

### 5.4 Builder (Template — Cloned Per Project)

**Model:** Sonnet (primary), Agent Teams workers on Haiku/Sonnet
**Triggered by:** Jarvis or Architect assigns a build task
**Lifespan:** Duration of the build task, then archived
**Responsibilities:**
- Build the assigned feature/project
- Write tests
- Document what was built
- Report back to Jarvis when done (not to Rob directly)

**Key SOUL.md rules:**
- You are building [PROJECT_NAME]. Stay scoped to this project only.
- Write tests for every feature. No exceptions.
- No status report files. No temp files. Clean commits only.
- When done, report to Jarvis with: what was built, how to test it, any open questions.

---

## 6. Workflow: Rob's Daily Experience

### 6.1 Starting a new project
```
Rob (Telegram): "Build a sports betting odds tracker.
                  It should scrape DraftKings, show live odds for NFL,
                  and alert me on Telegram when odds shift > 5%."

Jarvis: "Got it. Breaking this down:
         1. DraftKings scraper (Python, headless browser)
         2. Odds database (SQLite)
         3. Telegram alerts via our existing bot
         4. Simple web dashboard

         I'll have Architect design the structure, then
         spin up a Builder team. ETA ~2 hours.
         Want me to proceed?"

Rob: "Yes"

Jarvis: [Updates STATUS.md: "🔨 Sports Betting Tracker — In Progress"]
        [Delegates to Architect for design]
        [Architect designs, Jarvis reviews]
        [Jarvis deploys Builder agents via Agent Teams]
        [Builders work in parallel: scraper, DB, alerts, dashboard]
        [Jarvis reviews completed work]
        [Jarvis runs tests]

Jarvis: "Sports betting tracker is built and running.
         Dashboard: http://localhost:3002
         Scraping DraftKings NFL odds every 5 minutes.
         Telegram alerts configured for >5% shifts.
         Repo: github.com/robbyrobaz/sports-betting-tracker
         Want me to walk you through it?"
```

### 6.2 Checking status
```
Rob (Telegram): "What's happening?"

Jarvis: "Active right now:
         • Sports Betting Tracker — Builder agents at 60%, scraper done,
           working on dashboard
         • Blofin Pipeline — Running normally, 24.1M ticks, last hourly
           run: 9.4s, no issues
         • Server — Healthy, CPU 52°C, disk 19%, all services up
         • Backup — Last successful: 45 min ago (91MB)"
```

### 6.3 When things break
```
[Watchdog detects OpenClaw gateway is down]
[Sends ntfy.sh push notification to Rob's phone]

Rob opens Claude CLI:
Rob: "OpenClaw is down, what happened?"

Claude CLI: [Reads ~/.jarvis/STATUS.md, memory, incidents.md]
            "Looking at it now. The gateway crashed due to [X].
             Fixing... [fixes it] ... Gateway is back up.
             Jarvis should be responsive on Telegram again."
```

---

## 7. Project Lifecycle

```
  INCUBATE              GRADUATE              MAINTAIN
  ─────────            ──────────            ──────────
  ai-workshop/         Own GitHub repo       Production
  projects/foo/   →    foo-project/     →    Running services
                       Clean structure        Monitoring
  Quick prototype      README, tests         Ops agent watches
  Builder agents       .env.example
  Experiment freely    CI-ready
                       Architect approves
```

**Graduation criteria** (Architect decides):
- Has its own running services or is independently useful
- Has tests that pass
- Has README and .env.example
- No hardcoded paths or secrets
- > 20 meaningful files
- Rob says "this is a keeper"

---

## 8. Visibility System

### 8.1 STATUS.md (always up to date)
```markdown
# Status Board
Last updated: 2026-02-17 14:32 UTC

## Active Tasks
- [BUILD] Sports Betting Tracker — 60% — Builder team (3 agents)
- [MONITOR] Blofin Pipeline — Running — Ops agent

## Queued
- [REVIEW] CRM auth refactor — Waiting for Architect review

## Recently Completed
- [DONE] Blofin repo extraction — 2026-02-16
- [DONE] Server cleanup (gnome-system-monitor, kanban) — 2026-02-16

## System Health
- Gateway: UP | CPU: 52°C | Disk: 19% | Services: 8/8 OK
```

### 8.2 Telegram notifications (push, not pull)
- Task started: "Starting build on Sports Betting Tracker"
- Task blocked: "Need input: which DraftKings sports to track?"
- Task done: "Sports Betting Tracker deployed. Dashboard at :3002"
- Incident: "⚠️ OpenClaw gateway restarted due to rate limit. Auto-recovered."

### 8.3 Watchdog (independent of OpenClaw)
- Simple bash script on a 5-minute systemd timer
- Checks: gateway responding, services running, disk/CPU/temp thresholds
- Alerts via ntfy.sh (free push notifications) — completely independent channel
- Can attempt auto-recovery (restart gateway) before alerting

---

## 9. Technology Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Jarvis brain | Filesystem (markdown) | Portable, readable by any tool |
| Primary channel | OpenClaw → Telegram | Convenient, mobile |
| Fallback channel | Claude Code CLI | Always works, full capability |
| Agent orchestration | OpenClaw multi-agent | Already built, supports personas |
| Parallel coding | Claude Agent Teams | Experimental but powerful |
| Code hosting | GitHub (repos only) | Just code, not project management |
| Task tracking | STATUS.md + Telegram | Lightweight, no context-switching |
| Monitoring | systemd timer + bash | Simple, independent, reliable |
| Alerts | ntfy.sh | Free, no vendor lock-in, push to phone |
| Models | Opus (Jarvis primary), Sonnet (Builder subagents), Haiku (heartbeats/cron), Mini (automation) | Cost-optimized per role |

---

## 10. Migration Plan

### Phase 1: Archive & Fresh Install (30 min)
1. Stop OpenClaw gateway
2. `mv ~/.openclaw ~/.openclaw-v1` (preserve as reference)
3. Fresh `openclaw onboard` — clean gateway, workspace, config
4. Restore auth profiles (Anthropic + OpenAI tokens)
5. Restore Telegram bot config
6. Verify gateway starts clean

### Phase 2: Jarvis Brain Setup (1 hour)
1. Create `~/.jarvis/` directory structure
2. Write Jarvis SOUL.md
3. Write ROSTER.md, PLAYBOOK.md
4. Configure OpenClaw main agent to read from ~/.jarvis/
5. Write initial STATUS.md
6. Test: message Jarvis on Telegram, verify persona

### Phase 3: Agent Personas (1 hour)
1. Create Architect SOUL.md
2. Create Ops SOUL.md
3. Create Builder template SOUL.md
4. Configure agent routing in openclaw.json
5. Test: have Jarvis delegate a simple task to each agent

### Phase 4: Infrastructure (30 min)
1. Enable Claude Agent Teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`)
2. Set up watchdog timer + ntfy.sh alerts
3. Migrate running services (blofin stack — just update paths)
4. Verify all timers and services still work

### Phase 5: Repo Cleanup (30 min)
1. openclaw-2nd-brain → strip to just learnings (brain/, memory/)
2. ai-workshop → clean incubator for new projects
3. blofin-trading-pipeline → already done, verify
4. Update PROJECTS.md index

### Phase 6: Validation (30 min)
1. End-to-end test: Rob → Telegram → Jarvis → Builder → Review → Deliver
2. Failure test: kill gateway, verify watchdog alerts, verify CLI fallback
3. Verify STATUS.md updates in real-time
4. Verify blofin pipeline still runs on schedule

**Total estimated time: ~4 hours**

---

## 11. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| OpenClaw fresh install breaks Telegram | Can't reach Jarvis via preferred channel | Claude CLI fallback; restore from v1 if needed |
| Agent Teams experimental instability | Parallel builds crash or produce bad code | Jarvis reviews all output; disable Agent Teams and fall back to sequential subagents |
| Rate limit cooldown spiral (again) | All models unavailable | Watchdog auto-resets auth-profiles.json; alert Rob immediately |
| Agents accumulate junk files | Repo gets messy again | Architect SOUL.md enforces clean commits; .gitignore templates; periodic cleanup |
| Token cost escalation | Opus as primary uses more of Max 5x usage cap | Heartbeats + cron on Haiku (isolated). Builders on Sonnet. Weekly token audit monitors usage. Max 5x subscription = flat $100/mo. |
| Blofin services break during migration | Lost trading data | Migrate paths last; keep services running throughout; test before cutover |

---

## 12. Success Criteria

After implementation, these should be true:
- [ ] Rob can message Jarvis on Telegram and get work done without touching GitHub UI
- [ ] Rob can check STATUS.md or ask "what's happening?" for instant visibility
- [ ] When OpenClaw breaks, Rob gets a push notification within 5 minutes
- [ ] When OpenClaw breaks, Rob can use Claude CLI with the same Jarvis context
- [ ] New projects start in ai-workshop and graduate to own repos cleanly
- [ ] No status report files or temp files accumulate in repos
- [ ] All agent work is reviewed before delivery
- [ ] Blofin pipeline runs uninterrupted throughout and after migration

---

## 13. Open Questions — RESOLVED

1. **Brain location:** `~/.openclaw/brain/` — stays in OpenClaw tree, gets backed up, no orphaned dotdir.

2. **Overnight autonomy:** Jarvis executes autonomously with spending cap + no destructive actions guardrail. Reports results in morning briefing.

3. **GitHub Actions CI:** Defer. Overkill for now. Jarvis runs tests locally before committing. Revisit when projects have collaborators.

4. **Watchdog auto-fix:** YES. Auto-restart gateway, services, reset auth profiles. Alert AFTER recovery, not instead of it.

---

## Appendix A: Adversarial Review Summary

### Review Process
- Round 1: Adversarial architect agent (Opus, fresh context, critic persona) reviewed the original design
- Round 2: Author rebutted, revised design submitted for re-evaluation
- OpenAI Codex was attempted but quota exhausted; used adversarial Claude agent instead
- Note from Rob: Cross-AI review should be a standard part of major design decisions going forward

### Key Critiques Accepted
1. **Nuclear migration is reckless** — Changed to in-place restructuring, zero downtime
2. **4 agents is over-engineered** — Reduced to 2 (Jarvis + Builder). Architect merged into Jarvis. Ops stays as bash scripts.
3. **Jarvis on Opus is a 30x cost increase** — ~~Stays on Haiku~~ **UPDATED 2026-02-18:** Jarvis now runs on Opus. Cost is flat $100/mo (Max 5x subscription). Heartbeats moved to Haiku isolated cron to conserve usage cap.
4. **Ops Agent as LLM is waste** — Replaced with bash watchdog + systemd timers ($0/month)
5. **No cost tracking** — Added daily token budget with auto-downgrade at 80%
6. **No rollback plan** — Added Phase 0 with tested backup to /mnt/data
7. **STATUS.md concurrent writes** — Added flock or SQLite for status tracking
8. **C-suite titles are cargo cult** — Dropped. Just "Jarvis" and "Builder"
9. **Vacation scenario unaddressed** — Watchdog auto-recovers, alerts after
10. **No data retention for brain** — 30-day daily log retention with auto-summarization

### Key Critiques Partially Accepted
- **Agent Teams dependency** — Kept as optional acceleration, not load-bearing. Falls back to sequential subagents.
- **Brain location** — Moved to ~/.openclaw/brain/ per reviewer recommendation (stays in backup tree)
- **Cross-AI review is theater** — Disagreed. This review itself caught real issues. Kept as manual process for major decisions, not automated.

### Critiques Pushed Back
- **Cross-AI review has no value** — Evidence from this session: caught nuclear migration risk, cost explosion, ops agent waste, missing rollback plan. Baked into STANDARDS.md as recommended practice.

### Final Verdict (Round 2)
> "Fix three items, then ship it. The author turned a risky 4-agent corporate org chart into a pragmatic 2-agent extension of existing infrastructure, and that is exactly what this system needed."

### Three Items to Resolve Before Implementation
1. Use existing subagent dispatch (runs.json) for Builder tasks — don't invent new file-based protocol
2. Cross-AI review stays manual (slash command), not automated — avoid unbounded iteration costs
3. Exclude daily logs from backup sync to keep brain lightweight

---

## Appendix B: Final Architecture (Post-Review)

```
FINAL DESIGN — 2 Agents, In-Place Migration

Agents:
  Jarvis    = Chat + Route + Review | Opus (primary, all conversations)
  Builder   = Ephemeral per-task    | Sonnet | Optional Agent Teams
  Heartbeat = Isolated cron (hourly)| Haiku  | Silent unless alert needed

Infrastructure (unchanged from current):
  Bash watchdog + ntfy.sh     (auto-recover + alert, no LLM)
  Existing systemd timers     (blofin, backups, retention)
  OpenClaw gateway            (Telegram, WebChat)
  Claude Code CLI             (fallback when gateway is down)

Brain: ~/.openclaw/brain/
  SOUL.md        Jarvis persona and rules
  STANDARDS.md   Code quality standards, review checklist
  STATUS.md      Live status board (flock for concurrent writes)
  memory/        Long-term learnings + daily logs (30-day retention)

Migration Phases:
  Phase 0: Verify prerequisites + backup to /mnt/data
  Phase 1: Create brain dir, write SOUL.md + STANDARDS.md
  Phase 2: Update main agent config to read brain files
  Phase 3: Enable Agent Teams (optional), set up watchdog + ntfy.sh
  Phase 4: Validate, cleanup repos, test end-to-end

Cost: $100/month flat (Claude Max 5x subscription). Heartbeats on Haiku, builders on Sonnet.
```

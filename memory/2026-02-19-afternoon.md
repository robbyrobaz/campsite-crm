# 2026-02-19 Afternoon — Agent Stack Overhaul

## Major Changes

### Claw-Kanban Deployed
- **Service:** `claw-kanban.service` (systemd user), port 8787
- **Install path:** `/home/rob/.openclaw/workspace/kanban-dashboard/`
- **Database:** `kanban-dashboard/kanban.sqlite`
- **Features:** 6-column board, agent dispatch, real-time terminal viewer, OpenClaw gateway integration
- **Role routing:** All roles → Claude Code (configured via PUT /api/settings)
- Security audit done before install — clean (standard deps, 127.0.0.1 only, AES-256-GCM for OAuth)

### 5 Agent Files Created
- `.claude/agents/ml-engineer.md` (Sonnet) — Blofin + Numerai ML work
- `.claude/agents/dashboard-builder.md` (Sonnet) — Flask/React dashboards
- `.claude/agents/devops-engineer.md` (Sonnet) — omen-claw infrastructure
- `.claude/agents/qa-sentinel.md` (Sonnet) — Read-only QA gatekeeper
- `.claude/agents/crypto-researcher.md` (Sonnet) — Read-only + web research

### Enforcement Hook
- `.claude/hooks/enforce-tracking.sh` — logs Task spawns for audit trail
- Originally blocked Tasks unless PROJECTS.md updated; simplified to audit-only since kanban is the new tracking system

### Updated Operating Files
- **SOUL.md:** New workflow — kanban card → delegate → stay available → review
- **AGENTS.md:** Added kanban dispatch section (# prefix creates cards), updated boot sequence to include PROJECTS.md
- **HEARTBEAT.md:** Added "do NOT check blofin-stack-api" (removed Feb 18)
- **PROJECTS.md:** Created as high-level portfolio view (not task tracking — that's kanban now)
- **MEMORY.md:** Slimmed down to learnings only, project status moved to PROJECTS.md

## Rob's Key Feedback (Critical to Remember)
1. **"Current setup is horrible for me"** — couldn't see what I was working on, had to babysit, I kept forgetting tasks
2. **"I want a pretty dashboard"** — don't discount the visual tools from the research. A markdown file is not enough.
3. **"Do your job as COO"** — prioritize and execute autonomously, don't wait for instructions between tasks
4. **"Don't block the main session"** — I was unavailable for 5+ minutes running sleep commands waiting on Numerai. NEVER do this again. Spawn and move on.
5. **"Don't confuse old way and new way"** — kanban is the task system now, not status.json or PROJECTS.md for task tracking

## Numerai OOM Root Cause Found
- Full dataset (740 features × 6.6M rows) = ~29GB RSS → OOM killed the process AND the OpenClaw gateway
- Gateway auto-recovered (systemd restart)
- **Fix:** Switched to v2_equivalent_features (304 features), RSS dropped to ~10.7GB
- Run restarted (PID 401561), training in progress
- "medium" feature set in Numerai v5.1 IS 740 features (misleading name). v2_equivalent = 304, small = 42.

## Active Work at Session End
- **Blofin builder** (Sonnet, label: blofin-fixes): Fixing breakout strategies (root cause: all 3 have name="breakout" not versioned). Also bumping smoke test to 50K ticks.
- **Numerai full run** (PID 401561): Training with 304 features, ~10.7GB RSS
- **Kanban cards:** 5 created, 1 Done (Telegram config), 3 In Progress, 1 Planned (Numerai systemd service)

## Kanban Card IDs
- c_7e1918d15cb3b_19c76d8cdab — Blofin breakout fix (In Progress)
- c_2042f33d9dcf8_19c76d8cdd7 — Numerai full run (In Progress)
- c_222956f8e5246_19c76d8cdf9 — Numerai systemd service (Planned)
- c_ede385df10424_19c76d8ce1c — Telegram config (Done)
- c_5f5c09212d7bb_19c76d8ce41 — Smoke test bump (In Progress)

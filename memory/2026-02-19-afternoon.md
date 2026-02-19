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

## Blofin Backtest Bottleneck — Fixed
- **Root cause:** Pipeline never re-backtested T1 strategies. Phase 3 only checked stale `bt_*` columns.
- 9 of 22 T1 strategies had corrupt pre-fix data (millions of fake trades from BUY/SELL bug)
- **Fix:** Builder added Phase 2.5 (`phase2b_rebacktest_tier1()`) to `run_pipeline.py` — re-backtests T1 across 5 symbols at 500K ticks
- Created `blofin-stack-pipeline.timer` — runs every 2 hours at :15 (was only daily)
- **Gate concern:** Current T1→T2 gates (Sharpe≥0.5, EEP≥50) may be too strict — best T1s show Sharpe~0.27, EEP~39. May need calibration after fresh backtests.

## Numerai Full Run — OOM Root Cause + Index Bug
- **OOM (attempt 1-2):** 740 features × 6.6M rows = ~29GB RSS. OOM killed process AND gateway.
- **Fix:** Switched to v2_equivalent_features (304 features). RSS dropped to ~10.7GB.
- **Index bug (attempt 3):** Vanilla model completed (Sharpe 0.768, corr 0.01278 — strong!) but crashed in era-boosting. `dropna()` left non-contiguous pandas index, `model.predict()` returns 0-based numpy array → IndexError in `compute_era_weights()`.
- **Fix:** Added `reset_index(drop=True)` after dropna in `load_data()`. Reverted hacky indexing workaround.
- **Attempt 4:** Running (PID 430141) as of 15:00 MST.
- **Vanilla baseline on full data:** Sharpe 0.768, corr 0.01278, 494/628 positive eras. This alone may beat current live models.

## Blofin Quick Fixes — Done ✅
- Breakout strategies: renamed from all `name="breakout"` to `breakout_v1`, `breakout_v2`, `breakout_v3`
- Smoke test bumped from 5K to 50K ticks in `run_pipeline.py` (`limit_rows=50000`)
- 45 tests pass, committed `6d8db36`, pushed to main
- First builder (blofin-fixes) died silently (0 messages — known subagent reliability issue). Respawned as blofin-quick-fixes which completed in 87 seconds.

## Active Work at Session End
- **Numerai full run** (PID 430141, attempt 4): All 4 era-boost rounds complete, computing final ensemble metrics on 3.9M validation rows. Should finish soon.
- **Kanban status:** 4 Done, 1 In Progress (Numerai run), 1 Planned (Numerai systemd service)
- **Blofin pipeline timer:** Next run at 16:15 MST — will re-backtest 9 corrupt T1 strategies with fresh code

## Kanban Card IDs (updated)
- c_7e1918d15cb3b_19c76d8cdab — Blofin breakout fix ✅ Done
- c_2042f33d9dcf8_19c76d8cdd7 — Numerai full run (In Progress)
- c_222956f8e5246_19c76d8cdf9 — Numerai systemd service (Planned)
- c_ede385df10424_19c76d8ce1c — Telegram config ✅ Done
- c_5f5c09212d7bb_19c76d8ce41 — Smoke test bump ✅ Done
- c_1359b610a3ae9_19c77bdfaf3 — Backtest bottleneck ✅ Done

## Kanban Card IDs
- c_7e1918d15cb3b_19c76d8cdab — Blofin breakout fix (In Progress)
- c_2042f33d9dcf8_19c76d8cdd7 — Numerai full run (In Progress)
- c_222956f8e5246_19c76d8cdf9 — Numerai systemd service (Planned)
- c_ede385df10424_19c76d8ce1c — Telegram config (Done)
- c_5f5c09212d7bb_19c76d8ce41 — Smoke test bump (In Progress)

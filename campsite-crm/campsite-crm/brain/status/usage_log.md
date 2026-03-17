# Token Usage Log

> Manual snapshots to track daily burn rate. Compare before/after throttle changes.
> 7-day window resets: **March 1, 2026 @ 4:00 PM MST**

---

## All Throttle Changes (Mon Feb 23, 3:15–3:30 PM MST)

### Cron Schedule Changes
| Job | Before | After | How to revert |
|-----|--------|-------|---------------|
| Main session model | Opus | **Sonnet** | `openclaw session model opus` (or /model opus in chat) |
| Dispatch Pulse | every 15m | every 30m | `openclaw cron edit 36f47279... --every 15m` |
| Oversight Check | every 1h, wakes Opus main | every 2h, isolated Sonnet | `openclaw cron edit 4494f814... --every 1h --session main` |
| NQ Research Scientist | every 4h | every 6h | `openclaw cron edit 5a4344be... --cron "0 */4 * * *"` |
| Blofin Pipeline | every 2h | every 4h | `openclaw cron edit a566927f... --cron "15 */2 * * *"` |
| Auto-card creation (Phase 8) | enabled in dispatch prompt | **disabled** | Re-add Phase 8 block to dispatch prompt |

### Kanban Changes
| Change | Before | After | How to revert |
|--------|--------|-------|---------------|
| Auto QA review (claude-review) | Runs after every card succeeds | **Disabled** | Set `autoReview: true` in kanban settings via `python3 -c "import sqlite3,json; c=sqlite3.connect('kanban-dashboard/kanban.sqlite'); s=json.loads(c.execute('SELECT data FROM settings WHERE id=chr(109)+chr(97)+chr(105)+chr(110)').fetchone()[0]); s['autoReview']=True; c.execute('UPDATE settings SET data=? WHERE id=\"main\"',[json.dumps(s)]); c.commit()"` then restart claw-kanban.service |
| Cards after success | Move to Review/Test, spawn claude-review | **Go straight to Done** | Revert server/index.ts `handleRunComplete` — remove autoReview check |
| Deploy step in card prompt | Not present | **Injected per project_path** | Remove deploy block from prompt in server/index.ts |
| Max In Progress | 2 (was 3 before earlier throttle) | **1** | Update dispatch pulse --message to say "max 2" |
| Zombie card_run records | 229 stuck as "running" | Cleaned to "stopped" | N/A — cleanup only |

### Why These Were Made
- Pre-throttle burn: **44% of weekly quota in 2 days** (would hit 100% by Friday)
- Opus was 78% of cost — almost entirely main session conversation
- Kanban was running **258 separate Claude CLI spawns per day** (builder + reviewer per card)
- claude-review was failing >50% of time and duplicating builder's work
- 229 zombie "running" records were causing dispatch to spin on dead processes

---

## Snapshots

### PRE-THROTTLE BASELINE — Mon Feb 23, 3:15 PM MST

**7-day window (resets Mar 1):**
- All models: **44%** used
- Sonnet: **30%** used

**24-hour rolling (Sun Feb 22 → Mon Feb 23 ~3:15 PM):**
| Model | Requests | Tokens | Est. API Cost |
|-------|----------|--------|---------------|
| Opus | 965 | 105.5M | $173.51 |
| Sonnet | 849 | 86.4M | $49.78 |
| Haiku | 46 | 1.4M | $0.64 |
| **Total** | **1,864** | **193.2M** | **$223.92** |

**5-hour window (11 AM → 4 PM MST):**
| Model | Requests | Tokens | Est. API Cost |
|-------|----------|--------|---------------|
| Opus | 220 | 22.9M | $30.09 |
| Sonnet | 195 | 20.8M | $10.01 |
| Haiku | 11 | 0.5M | $0.25 |
| **Total** | **426** | **44.2M** | **$40.35** |

**Key ratios (pre-throttle):**
- Opus = 78% of token cost
- ~$224/day equivalent API cost
- ~40 Opus requests/hour

---

### POST-THROTTLE — _(fill in tomorrow)_

**Date:** Tue Feb 24
**7-day window:**
- All models: __%
- Sonnet: __%

**24-hour rolling:**
| Model | Requests | Tokens | Est. API Cost |
|-------|----------|--------|---------------|
| Opus | | | |
| Sonnet | | | |
| Haiku | | | |
| **Total** | | | |

**Notes:**

---

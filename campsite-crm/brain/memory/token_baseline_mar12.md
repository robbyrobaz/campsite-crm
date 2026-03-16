# Token Usage Baseline — Mar 12, 2026 10:03 AM

**Purpose:** Track token usage after switching all models to Haiku. Check back in a few hours to see burn rate and verify we have headroom.

## Baseline Snapshot (10:03 AM MST)

### 7-Day Window
| Metric | Value |
|--------|-------|
| Total % | 96.0% 🔴 |
| Sonnet % | 92.0% 🔴 |
| Other models % | ~4.0% ✅ |
| Reset time | Mar 12 9:00 PM MST (11 hours from now) |

### 5-Hour Window
| Model | Tokens | Requests | Cost |
|-------|--------|----------|------|
| Haiku | 9.7M | 332 | $2.49 |
| Sonnet | 2.0M | 47 | $1.23 |
| Total | 11.7M | 379 | $3.72 |
| % of limit | 7.0% ✅ | — | — |
| Reset time | Mar 12 1:00 PM MST (3 hours from now) |

### 24-Hour Window
| Model | Tokens | Requests | Cost |
|-------|--------|----------|------|
| Haiku | 11.8M | 371 | $2.99 |
| Sonnet | 2.6M | 67 | $1.72 |
| Total | 14.4M | 438 | $4.71 |

## Decision Made

**Switched ALL models to Haiku.** Builders, crons, everything → `claude-haiku-4-5`.

**Why this works:**
- Sonnet quota: 92% (was the bottleneck, stays unchanged)
- Haiku quota: ~4% (fresh, separate limit, 2.4x cheaper per token)
- Moving builders from Sonnet → Haiku offloads quota pressure to a less-constrained bucket

## Check-In Plan

**Next review: ~1-2 PM MST (after 5h reset and continuing dispatch)**

Expected by then:
- 5h window should reset to ~0% (fresh window)
- 7-day should creep up slightly from Haiku usage
- Sonnet should stay flat (only this main session using it)

**Success criteria:** Haiku usage in 7-day stays <20% while we dispatch work. Confirms we have quota headroom.

---
*Baseline set 10:03 AM. Check back in 3h.*

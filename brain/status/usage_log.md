# Token Usage Log

> Manual snapshots to track daily burn rate. Compare before/after throttle changes.
> 7-day window resets: **March 1, 2026 @ 4:00 PM MST**

---

## Throttle Changes Applied (Mon Feb 23, ~3:15 PM MST)

| Change | Before | After |
|--------|--------|-------|
| Main session model | Opus | **Sonnet** |
| Dispatch Pulse | every 15m, Sonnet | every 30m, Sonnet |
| Oversight Check | every 1h, wakes **Opus main** | every 2h, **isolated Sonnet** |
| NQ Research Scientist | every 4h | every 6h |
| Blofin Pipeline | every 2h | every 4h |
| Auto-card creation (Phase 8) | enabled | **disabled** |

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

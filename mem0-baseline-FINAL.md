# Mem0 Installation Baseline — April 1, 2026 09:24 MST

## Installation Timestamp
- **Installed:** 2026-04-01 09:14 MST
- **Gateway Restarted:** 2026-04-01 09:15 MST
- **Baseline Captured:** 2026-04-01 09:24 MST
- **Baseline Data:** `mem0-baseline-sessions.json` (247 sessions tracked)

## Critical Context: WHY NOW IS THE BEST TIME

**You're at 94% of 7-day quota** — this is EXACTLY when Mem0 should help most!
- High usage = lots of context to compress
- Near limit = every token saved matters
- Perfect testing conditions = can measure impact immediately

## Token Usage BEFORE Mem0 (Subscription Level)

### Claude Max 20x Subscription Status (AS OF 09:20 MST)
- **5-hour window:** 12.0% used
- **7-day (all models):** 94.0% used ⚠️ **CRITICAL**
- **7-day (Sonnet only):** 80.0% used ⚠️

### What This Means
- **6% runway left** on all-models quota (~6-12 hours at current rate)
- **20% runway on Sonnet** (~24-36 hours at current rate)
- **Limit will hit soon** regardless of Mem0 — this tests if it can extend runway

## Session-Level Token Usage (Actual Data)

### All Sessions (247 total as of 09:24 MST)

**By Agent:**
- **Church:** 123 sessions, 2.3M total tokens (mostly output: 27.9K out vs 1.9K in)
- **Crypto:** 86 sessions, 2.2M total tokens (138.7K output vs 2.6K input)
- **NQ:** 17 sessions, 920K total tokens (687K input! vs 122K output)
- **Main (Jarvis):** 13 sessions, 394K total tokens (273K input vs 29K output)
- **SP:** 8 sessions, 360K total tokens (3.5M input! — likely bulk FT sessions)

**By Model:**
- **Claude Sonnet 4.5:** 228 sessions, 5.4M tokens (271K output, 5.7K input avg)
- **Claude Opus 4.6:** 6 sessions, 248K tokens (48K output, 90 input — big outputs!)
- **Nemotron-3-super (free):** 4 sessions, 240K tokens (52K output, 4.5M input — builders)
- **Claude Opus 4.5:** 1 session, 108K tokens
- **Claude Haiku 4.5:** 5 sessions, 96K tokens
- **DeepSeek R1 (free):** 1 session, 17K tokens

### Key Observations
1. **Input tokens dominate for NQ/SP** — lots of context being loaded (687K + 3.5M)
2. **Main session moderate** — 273K input is high but not extreme
3. **Sonnet is 90% of usage** — 5.4M / 6.1M total tokens
4. **Church/Crypto mostly output** — small inputs, larger responses

### Where Mem0 Should Help Most
1. **NQ sessions** — 687K input tokens suggest heavy context loading
2. **SP sessions** — 3.5M input (bulk FT) won't benefit much (data processing)
3. **Main session** — 273K input over 13 sessions = good compression target
4. **Output tokens unchanged** — Mem0 can't reduce response length

## Mem0 Configuration

### Plugin Details
- **Version:** 0.4.1 (@mem0/openclaw-mem0)
- **Install Path:** /home/rob/.openclaw/extensions/openclaw-mem0
- **Memory Slot:** Replaced memory-core (memory-core and memory-lancedb disabled)

### Local Open-Source Mode Settings
```json
{
  "mode": "open-source",
  "userId": "jarvis-main",
  "autoCapture": true,
  "autoRecall": true,
  "oss": {
    "embedder": {
      "provider": "ollama",
      "model": "nomic-embed-text"
    },
    "vectorStore": {
      "provider": "chroma",
      "path": "/home/rob/.openclaw/mem0_chroma_db"
    },
    "llm": {
      "provider": "anthropic",
      "model": "claude-sonnet-4-5"
    }
  }
}
```

### Hardware Resources
- **CPU:** AMD (Package id 0 temp: 53°C at baseline)
- **GPU:** RTX 2080 Super (0% load, 823MB/8GB VRAM = 10% — Ollama embedder loaded)
- **RAM:** 31GB total (7.1GB used = 23%)
- **Disk:** 468GB total, 366GB used (78GB free), 83% usage

## Expected Impact

### What Mem0 Should Help With
1. **Input token compression** — inject only relevant memories vs full context files
2. **Session continuity** — memories survive context compaction/pruning
3. **Semantic recall** — better than file-based search for relevant context

### What Mem0 WON'T Help With
1. **Output tokens** — response length unchanged (quality maintained)
2. **Extraction cost** — uses Sonnet to summarize conversations (adds tokens)
3. **Conversation volume** — if Rob asks 100 questions, that's still 100 API calls
4. **Data processing** — SP bulk FT sessions won't benefit (processing not conversation)

### Realistic Expectations
- **Best case:** 30-50% reduction in INPUT tokens for conversational sessions
- **Main session:** Could drop from 273K/13 = 21K avg input to ~10-15K avg
- **NQ/Crypto agents:** Should see input reduction on status/question sessions
- **Net impact:** 15-25% total token reduction (input is ~50% of conversational load)
- **Break-even risk:** Extraction overhead might offset savings on short sessions

## Measurement Plan

### Checkpoints
1. **6 hours (15:24 MST today):** Check 5-hour window — should stay ≤12% if helping
2. **24 hours (09:24 MST tomorrow):** Check 7-day trend — growth rate should slow
3. **48 hours (09:24 MST Apr 3):** Final assessment — keep vs rollback

### Success Metrics
- **5-hour windows stay low** — <12% consistently vs climbing to 15-20%
- **7-day quota slows** — grows <2%/day instead of 6%/day
- **Session input tokens drop** — compare main/NQ/Crypto avg input per session
- **Response quality maintained** — no context loss, correct recall

### Warning Signs (Rollback If...)
1. **7-day usage climbs FASTER** — extraction overhead > compression savings
2. **5-hour windows grow** — 15-20% windows instead of staying <12%
3. **Response quality degrades** — missing context, wrong answers
4. **Responses slower** — embedding/search adds noticeable latency

## Monitoring Commands

```bash
# Check Mem0 vector DB size
du -sh /home/rob/.openclaw/mem0_chroma_db/

# Check Ollama status
ollama list | grep nomic-embed-text
ps aux | grep ollama

# Gateway logs for Mem0 activity
journalctl --user -u openclaw-gateway.service --since "1 hour ago" | grep -i mem0

# Session stats (compare to baseline)
openclaw sessions --json --all-agents 2>/dev/null | jq '{
  sessions: [.sessions[] | {agent: .agentId, model, input: .inputTokens, output: .outputTokens}]
}' | jq '.sessions | group_by(.agent) | map({agent: .[0].agent, total_input: (map(.input // 0) | add)})'

# Quick session status
# Via webchat: just ask "session status"
```

## Rollback Plan

If Mem0 doesn't help or makes things worse:

```bash
# Restore backup config
cp /home/rob/.openclaw/openclaw.json.bak /home/rob/.openclaw/openclaw.json

# Restart gateway
openclaw gateway restart

# Verify memory-core is back
openclaw plugins list | grep memory
```

## Files
- **Baseline sessions:** `mem0-baseline-sessions.json` (247 sessions, full token data)
- **Baseline summary:** `mem0-baseline-FINAL.md` (this file)
- **Config backup:** `/home/rob/.openclaw/openclaw.json.bak`

## Reality Check

**Starting at 94% quota is PERFECT for testing:**
- High usage = maximum opportunity for compression savings
- Near limit = every token saved extends runway
- Clear measurement = can see impact within hours, not days
- High stakes = if it doesn't help, we'll know fast

**If Mem0 saves 20% of input tokens:**
- Main session: 273K → 218K input (55K saved over 13 sessions)
- NQ sessions: 687K → 550K input (137K saved over 17 sessions)
- **Total:** ~200K tokens saved across all sessions
- **Impact:** Could extend runway from 6 hours to 8-10 hours

**If extraction overhead offsets savings:**
- Extraction cost: ~500-1000 tokens per conversation turn
- 247 sessions × 500 tokens = 123K tokens added
- Net savings: 200K - 123K = 77K tokens (~12% net benefit)

**Bottom line:** Even modest savings matter at 94% usage. Let's measure and see!

---

**Next checkpoint:** April 1, 2026 15:24 MST (6 hours) — check if 5-hour window stayed ≤12%

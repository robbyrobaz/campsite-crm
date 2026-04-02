# Mem0 Installation Baseline — April 1, 2026 09:24 MST

## Status Update — April 1, 2026 16:26 MST

Mem0 is now active on live OpenClaw chat sessions for Jarvis and agent chats, but the implementation is no longer the original OSS Mem0 path from this morning.

## A/B Benchmark Update — April 1, 2026 16:40 MST

A controlled scratch-session benchmark was run against `openai-codex/gpt-5.4` using the NQ agent path. The benchmark confirmed that auto capture and auto recall are active, but it did **not** show token savings in its current form.

### Benchmark result
- Report: `research/mem0_ab/mem0_ab_report_20260401-1640.json`
- Baseline follow-up turn (`no mem`, repeated context in prompt):
  - `3507` uncached input tokens
  - `24320` cache-read tokens
  - `$0.015883`
- With-memory follow-up turn (`mem on`, short follow-up prompt):
  - `24482` uncached input tokens
  - `0` cache-read tokens
  - `$0.062240`

### Why the result is not a clean final verdict
- The current memory implementation is storing and reinjecting large raw transcript blocks, not compact fact summaries.
- That made the with-memory follow-up prompt much larger than intended.
- The NQ agent also invoked `memory_store` / `memory_search` tools on its own in the baseline arm, which contaminates an attempt to isolate automatic plugin savings.
- The no-memory arm got a large provider prompt-cache hit, which further biases the comparison.

### Practical conclusion
- Current state proves **memory is active**.
- Current state does **not yet prove memory saves tokens**.
- The next meaningful optimization is to shrink stored memories and recalled payloads into compact facts instead of raw transcript chunks.

### What changed from the original install
- The original `@mem0/openclaw-mem0` OSS path did not work reliably in this environment.
- Trigger filtering was preventing live webchat recall/capture.
- The OSS extraction path also failed with `Anthropic API key is required` and intermittent `fetch failed` errors.
- The installed plugin bundle was patched so live chat recall/capture now uses a simple durable local store instead of the unstable OSS extraction/vector path.

### Current working memory path
- Plugin bundle: `/home/rob/.openclaw/extensions/openclaw-mem0/dist/index.js`
- Durable store: `/home/rob/.mem0-local/memories.json`
- Current store status at 16:26 MST:
  - `12` total records
  - `7` for `jarvis-main`
  - `1` for `jarvis-main:agent:nq`
  - `1` for `jarvis-main:agent:crypto`
  - `3` for `jarvis-main:agent:church`

### Live proof from gateway logs
- `openclaw-mem0: auto-captured 1 memories`
- `openclaw-mem0: injecting 1 memories into context`
- `openclaw-mem0: injecting 2 memories into context`
- `openclaw-mem0: injecting 3 memories into context`

This confirms the current plugin is now participating in real OpenClaw chat turns.

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

## Original Mem0 Configuration

### Plugin Details
- **Version:** 0.4.1 (@mem0/openclaw-mem0)
- **Install Path:** /home/rob/.openclaw/extensions/openclaw-mem0
- **Memory Slot:** Replaced memory-core (memory-core and memory-lancedb disabled)

### Local Open-Source Mode Settings At Install Time
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

## Current Reality

The original plan assumed:
- local Ollama embeddings
- local vector DB
- Anthropic-backed fact extraction

That did not hold up in practice. The part that is working now is:
- local durable memory store
- live recall injection before replies
- live capture after replies
- no Anthropic API dependency for memory extraction

This means the token-savings test is now cleaner:
- no extra Anthropic extraction overhead
- any benefit now comes from recall/continuity reducing repeated context reconstruction

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

### What It WON'T Help With
1. **Output tokens** — response length unchanged (quality maintained)
2. **Output tokens** still dominate on long answers
3. **Conversation volume** — if Rob asks 100 questions, that's still 100 API calls
4. **Data processing** — SP bulk FT sessions won't benefit (processing not conversation)

### Realistic Expectations
- **Best case:** 30-50% reduction in INPUT tokens for conversational sessions
- **Main session:** Could drop from 273K/13 = 21K avg input to ~10-15K avg
- **NQ/Crypto agents:** Should see input reduction on status/question sessions
- **Net impact:** most likely visible in repeated follow-up chats, not one-off tasks
- **Break-even risk:** much lower now because the current path does not depend on Anthropic extraction

## Measurement Plan

### What to measure now

The correct question is not just "does memory exist?"

The real question is:
- do repeated Jarvis/NQ follow-up chats use fewer input tokens than they did before memory worked?

### Best measurement method

Use the baseline session data from this morning, then compare it against new post-fix sessions.

Baseline files:
- `mem0-baseline-sessions.json`
- `mem0-baseline-FINAL.md`

Working-memory start time:
- approximately **2026-04-01 16:24 MST**

So the clean comparison is:
1. pre-working-memory sessions: before `2026-04-01 16:24 MST`
2. post-working-memory sessions: after `2026-04-01 16:24 MST`

### Primary metrics

1. **Average input tokens per conversational session**
- especially for `main` and `nq`
- this is the most important metric

2. **Average total tokens per session**
- useful secondary check

3. **Repeated follow-up question behavior**
- ask the same domain follow-ups in new sessions
- check whether the agent avoids reloading/explaining large background context

4. **Memory activity count**
- how often recall/capture actually fires

### Recommended command checks

Check live memory activity:

```bash
rg -n 'openclaw-mem0: (auto-captured|injecting [0-9]+ memories into context)' /tmp/openclaw/openclaw-$(date +%F).log | tail -n 40
```

Check store contents:

```bash
python3 - <<'PY'
import json
p='/home/rob/.mem0-local/memories.json'
data=json.load(open(p))
print('total', len(data))
for k in sorted({r.get('user_id') for r in data}):
    print(k, sum(1 for r in data if r.get('user_id')==k))
PY
```

Inspect current session usage:

```bash
jq '.["agent:main:main"], .["agent:nq:main"]' /home/rob/.openclaw/agents/main/sessions/sessions.json /home/rob/.openclaw/agents/nq/sessions/sessions.json
```

### Practical comparison to run tomorrow

Compare:
- Jarvis sessions created after `2026-04-01 16:24 MST`
- NQ sessions created after `2026-04-01 16:24 MST`

against the session averages captured in `mem0-baseline-sessions.json`.

If memory is helping, the pattern should be:
- fewer input tokens on follow-up sessions
- fewer repeated long restatements of background context
- more answers that begin from remembered state rather than rebuilding it

### Checkpoints
1. **Today:** confirm recall/capture keeps firing in live chats
2. **Tomorrow morning:** compare post-16:24 Jarvis/NQ sessions against baseline
3. **After 24-48 hours:** decide whether to keep this local memory path

### Success Metrics
- **Session input tokens drop** — compare main/NQ average input per session
- **Recall actually fires** — gateway logs show `injecting ... memories into context`
- **Response quality maintained** — no context loss, correct recall
- **Reduced repeated setup** — less re-explaining in fresh sessions

### Warning Signs (Rollback If...)
1. **Session input tokens do not improve**
2. **Recall noise grows** — bad or irrelevant memories injected
3. **Response quality degrades** — missing or wrong remembered context
4. **Memory store grows with low-signal junk**

## Monitoring Commands

```bash
# Memory activity
rg -n 'openclaw-mem0: (auto-captured|injecting [0-9]+ memories into context)' /tmp/openclaw/openclaw-$(date +%F).log | tail -n 40

# Store summary
python3 - <<'PY'
import json
p='/home/rob/.mem0-local/memories.json'
data=json.load(open(p))
print('total', len(data))
for k in sorted({r.get('user_id') for r in data}):
    print(k, sum(1 for r in data if r.get('user_id')==k))
PY

# Quick session status
# Via webchat: ask "session status"
```

## Rollback Plan

If the current memory path doesn't help or makes things worse:

```bash
# revert /home/rob/.openclaw/extensions/openclaw-mem0/dist/index.js
# restart gateway
# re-test without memory injection
```

## Files
- **Baseline sessions:** `mem0-baseline-sessions.json` (247 sessions, full token data)
- **Baseline summary:** `mem0-baseline-FINAL.md` (this file)
- **Config backup:** `/home/rob/.openclaw/openclaw.json.bak`
- **Live store:** `/home/rob/.mem0-local/memories.json`

## Reality Check

**Important correction:** the current working memory path is not the same as the original morning design.

The original install assumptions in this file are still useful as a historical baseline, but current measurement should be based on:
- live recall/capture behavior
- session input-token changes after 16:24 MST
- quality of remembered context in new sessions

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

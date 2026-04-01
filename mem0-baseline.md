# Mem0 Installation Baseline — April 1, 2026 09:20 MST

## Installation Timestamp
- **Installed:** 2026-04-01 09:14 MST
- **Gateway Restarted:** 2026-04-01 09:15 MST
- **Baseline Captured:** 2026-04-01 09:20 MST (CORRECTED)

## Token Usage BEFORE Mem0 (Actual Numbers)

### Claude Max 20x Subscription Status (AS OF 09:20 MST)
- **5-hour window:** 12.0% used
- **7-day (all models):** 94.0% used ⚠️
- **7-day (Sonnet only):** 80.0% used ⚠️

### Critical Context
- **EXTREMELY close to limit** — 94% of 7-day quota consumed
- **6% remaining** until hard limit (likely hits limit within hours)
- **Sonnet at 80%** — 20% headroom on Sonnet-specific limit
- **Primary driver:** Heavy main session usage (mix of Opus/Sonnet)

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

### Components
- **Embeddings:** nomic-embed-text via Ollama (274MB model, local GPU)
- **Vector DB:** ChromaDB at /home/rob/.openclaw/mem0_chroma_db
- **Extraction LLM:** Claude Sonnet 4.5 (uses Anthropic API for fact extraction)

## Expected Impact

### What Mem0 Should Help With
1. **Context compression:** Inject only relevant memories vs full MEMORY.md/BOOTSTRAP.md
2. **Input token reduction:** Smaller context sent to Claude on every turn
3. **Compaction resistance:** Memories survive OpenClaw's context management
4. **Auto-capture/recall:** Hands-off memory management

### What Mem0 WON'T Help With (Important!)
- **Output tokens:** Still generated at same rate (responses same length)
- **Extraction cost:** Uses Sonnet tokens for fact extraction after conversations
- **Conversation volume:** If Rob asks 100 questions, Mem0 can't reduce that
- **Model choice:** Opus vs Sonnet cost difference unchanged

### Realistic Expectations
- **Best case:** 30-50% reduction in INPUT tokens (context compression)
- **Output tokens:** No change (response quality maintained)
- **Net savings:** 15-25% total token reduction (input is ~50% of total)
- **Break-even:** Extraction overhead vs context savings

## Measurement Plan (Next 24-48 Hours)

### Success Metrics
1. **7-day quota drops** — if we're at 94% now, should see slower climb
2. **5-hour windows smaller** — compare 5h usage before/after
3. **Sonnet-only percentage** — should see reduction in Sonnet input tokens
4. **Context size** — check session_status for context usage trends

### Key Comparison Points
- **Baseline (now):** 94% 7-day, 80% Sonnet, 12% 5-hour
- **After 6 hours:** Check 5-hour window (should be <12% if helping)
- **After 24 hours:** Check 7-day trend (should grow slower than 6%/day)

### Monitoring Commands
```bash
# Check Mem0 vector DB size
du -sh /home/rob/.openclaw/mem0_chroma_db/

# Check Ollama embedder status
ollama list | grep nomic-embed-text

# Gateway logs for Mem0 activity
journalctl --user -u openclaw-gateway.service --since "1 hour ago" | grep -i mem0

# Session status (token usage)
# Via webchat: ask for session status
```

### Warning Signs (Consider Rollback If...)
1. **7-day usage INCREASES faster** — extraction overhead > savings
2. **Response quality degrades** — missing context, wrong answers
3. **Responses get slower** — embedding/search overhead too high
4. **GPU thermal issues** — Ollama + other GPU work causing problems

## Rollback Plan (If Needed)
1. Restore config backup: `cp /home/rob/.openclaw/openclaw.json.bak /home/rob/.openclaw/openclaw.json`
2. Restart gateway: `openclaw gateway restart`
3. Re-enable memory-core if desired via config

## Notes
- **Old MEMORY.md files untouched** — still in workspace, just not actively used by memory tools
- **memory-core disabled** — Mem0 owns the "memory" tool slot exclusively
- **Extraction uses Anthropic tokens** — summarization step after each conversation
- **Embeddings are free** — local Ollama + GPU, zero API cost
- **Started at CRITICAL quota level** — 94% means very little runway to test

## Test Scenarios (To Try)
1. Ask about something from yesterday's conversation (memory recall test)
2. Long multi-turn conversation (watch context compression vs extraction cost)
3. Check session_status frequently to track token deltas
4. Compare 5-hour windows: 12% baseline vs 6h from now

---

**Reality Check:** We're at 94% of 7-day limit. If Mem0 doesn't help, we'll hit the limit regardless within ~12 hours. This is a high-stakes test.

**Next Check:** April 1, 2026 15:20 MST (6 hours later) — check 5-hour window
**Daily Check:** April 2, 2026 09:20 MST (24h later) — compare 7-day trend
**Final Assessment:** April 2-3, 2026 — decide keep vs rollback based on actual data

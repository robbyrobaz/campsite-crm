# Mem0 Installation Baseline — April 1, 2026 09:16 MST

## Installation Timestamp
- **Installed:** 2026-04-01 09:14 MST
- **Gateway Restarted:** 2026-04-01 09:15 MST
- **Baseline Captured:** 2026-04-01 09:16 MST

## Token Usage Before Mem0

### Current Session (agent:main:main)
- **Tokens this turn:** 21 in / 595 out
- **Cache:** 100% hit rate (89k cached, 261 new)
- **Context:** 100k/200k (50%)
- **Compactions:** 0

### Claude Max 20x Subscription Status
- **All-models quota:** 69% used (as of Apr 1 ~07:00 MST)
- **Sonnet 7-day limit:** 47% used (as of Apr 1 ~07:00 MST)
- **Primary usage:** Main Jarvis session on Opus/Sonnet
- **Projected limit hit:** Tuesday ~3 AM (41h before reset at time of measurement)

### Recent Heavy Usage Patterns (Pre-Mem0)
- **Main session model:** Opus 4.6 (234/265 requests in 24h = 88% of usage)
- **Builder sessions:** Nemotron-3-super-120b-a12b (free, zero Anthropic cost)
- **Cron heartbeats:** Haiku 4.5 (cheap)
- **Issue:** High main-session volume driving quota consumption

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
- **CPU:** AMD (Package id 0 temp: 85°C at baseline)
- **GPU:** RTX 2080 Super (for local embeddings)
- **RAM:** 31GB total (23GB available at baseline)
- **Disk:** 468GB total, 366GB used (78GB free), 83% usage

### Components
- **Embeddings:** nomic-embed-text via Ollama (274MB model, local GPU)
- **Vector DB:** ChromaDB at /home/rob/.openclaw/mem0_chroma_db
- **Extraction LLM:** Claude Sonnet 4.5 (uses Anthropic API for fact extraction)

## Expected Benefits (Per Grok/Mem0 Docs)
1. **Context compression:** Inject only relevant memories vs full MEMORY.md
2. **Token reduction:** 60-90% savings on context in long sessions (claimed)
3. **Compaction resistance:** Memories survive OpenClaw's context management
4. **Auto-capture/recall:** Hands-off memory management

## Measurement Plan (Next 2-3 Days)

### Success Metrics
1. **Token usage drops** — compare daily totals vs pre-Mem0 baseline
2. **Response quality maintained** — no loss of context/accuracy
3. **Memory recall working** — asks about past conversations get correct answers
4. **No performance degradation** — response times stay reasonable

### Monitoring Commands
```bash
# Check Mem0 vector DB size
du -sh /home/rob/.openclaw/mem0_chroma_db/

# Check Ollama embedder status
ollama list | grep nomic-embed-text

# Gateway logs for Mem0 activity
journalctl --user -u openclaw-gateway.service --since "1 hour ago" | grep -i mem0

# Session status (token usage)
# Via webchat: just ask for session status
```

### Rollback Plan (If Needed)
1. Restore config backup: `cp /home/rob/.openclaw/openclaw.json.bak /home/rob/.openclaw/openclaw.json`
2. Restart gateway: `openclaw gateway restart`
3. Re-enable memory-core if desired via config

## Notes
- **Old MEMORY.md files untouched** — still in workspace, just not actively used by memory tools
- **memory-core disabled** — Mem0 owns the "memory" tool slot exclusively
- **Extraction uses Anthropic tokens** — summarization step after each conversation
- **Embeddings are free** — local Ollama + GPU, zero API cost

## Test Scenarios (To Try)
1. Ask about something from yesterday's conversation
2. Long multi-turn conversation (watch context compression)
3. Ask "what do you know about X" where X was discussed days ago
4. Check `/api/status` or session_status for token deltas

---

**Next Check:** April 2, 2026 (24h later) — compare token usage
**Final Assessment:** April 3-4, 2026 (72h later) — decide keep vs rollback

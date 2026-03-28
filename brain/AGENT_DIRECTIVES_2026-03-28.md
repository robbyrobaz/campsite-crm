# Agent Directives — March 28, 2026 (Per Rob)

**Issued:** 2026-03-28 08:05 MST  
**Authority:** Rob (owner)  
**Scope:** ALL agents (Jarvis, NQ, Crypto, SP, Church)

---

## Directive: Mandatory Session Context Protocol

**Problem:** Agents waking up "fresh" without current context, leading to repeated questions and missed state.

**Solution:** Simple timestamp-based BOOTSTRAP freshness checking.

**What changed:**
1. ✅ All agent BOOTSTRAP.md files now have "Last updated: YYYY-MM-DD HH:MM MST" timestamp headers
2. ✅ Every session MUST verify timestamp is <24h old
3. ✅ If stale, agent updates BOOTSTRAP by checking current state
4. ✅ Use OpenClaw's built-in `memory_search(query)` tool for deep context retrieval
5. ❌ NO symlinks (fragile, breaks on git ops, not standard)
6. ❌ NO verification scripts (over-engineered)
7. ❌ NO session summaries (daily memory already does this)

**Mandatory session startup checklist (all agents):**
1. Read SOUL.md
2. Read BOOTSTRAP.md → verify timestamp <24h
3. Read MEMORY.md (auto-injected by OpenClaw)
4. Read memory/YYYY-MM-DD.md (today + yesterday)
5. Use `memory_search(query)` when context needed

**Why this approach:**
- ✅ Simple (just add timestamps)
- ✅ Standard (aligns with OpenClaw's design)
- ✅ Robust (no symlinks, no scripts to break)
- ✅ Universal (works for all agents, repos or not)

**Reference:** `/home/rob/.openclaw/workspace/brain/AGENT_CONTEXT_PROTOCOL.md`

**Enforcement:** Effective immediately. All agents MUST follow this protocol.

**Status:**
- ✅ Jarvis workspace: BOOTSTRAP.md created, AGENTS.md updated
- ✅ NQ workspace: BOOTSTRAP.md timestamp added
- ✅ Crypto workspace: BOOTSTRAP.md already had timestamps
- ✅ SP workspace: BOOTSTRAP.md timestamp added, committed to git
- ✅ Church workspace: BOOTSTRAP.md already had timestamps (needs refresh)

**Next steps:**
- Agents will see updated AGENTS.md on next session boot
- NQ agent's symlink/verification approach is REJECTED
- Use this simple approach going forward

---

**Rob's instruction:** "yes, I like your simpler plan, enforce it to all agents, however you see fit. be mindful of what they think is already working, and tell them this is how it must be done, per Rob."

**Enforced:** 2026-03-28 08:05 MST by Jarvis

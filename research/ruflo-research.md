# Ruflo Research — March 23, 2026

**Repo:** https://github.com/ruvnet/ruflo  
**Status:** Evaluated and rejected  
**For:** Claude Code multi-agent orchestration

---

## What Is Ruflo?

**"Enterprise AI Orchestration Platform"** — A self-learning agent framework that transforms Claude Code into a multi-agent development system.

**Key tagline:** *Deploy 60+ specialized agents in coordinated swarms with self-learning capabilities, fault-tolerant consensus, and enterprise-grade security.*

---

## Claimed Capabilities

### 🤖 Multi-Agent System
- **60+ specialized agents** (coder, tester, reviewer, architect, security, etc.)
- **Swarm coordination** — agents work together via hierarchical or mesh topologies
- **Queen-led hierarchy** — strategic/tactical/adaptive queen agents coordinate workers
- **Fault-tolerant consensus** — Byzantine consensus handles up to 1/3 failing agents

### 🧠 Self-Learning Intelligence
- **SONA** (Self-Optimizing Neural Architecture) — learns which agents work best for each task
- **EWC++** — prevents forgetting successful patterns
- **Mixture of Experts** (MoE) — 8 specialized expert networks route work
- **Flash Attention** — 2-7x faster reasoning
- **HNSW vector search** — sub-millisecond pattern retrieval

### 💾 Memory & Learning
- **Vector memory** — HNSW-indexed pattern storage
- **Knowledge graph** — PageRank + community detection for influential insights
- **AgentDB** — persistent SQLite/PostgreSQL memory with 77+ SQL functions
- **3-scope memory** — project/local/user isolation with cross-agent transfer
- **Hyperbolic embeddings** — Poincaré ball for hierarchical code relationships

### ⚡ Performance Optimization (Key Claim)
- **Agent Booster (WASM)** — simple code transforms skip LLM entirely (<1ms vs 2-5s)
- **3-tier model routing** — simple tasks → free WASM, medium → Haiku, complex → Opus
- **Token optimizer** — 30-50% token reduction via compression + caching
- **Cost savings** — 75% lower API costs, 2.5x Claude Max extension

---

## Evaluation Results (March 23, 2026)

### Installation: ✅ Successful
- **Size:** 65MB (minimal install, `--omit=optional`)
- **Version:** v3.5.42
- **Install time:** 22 seconds
- **Location:** `~/.openclaw-ruflo/` (isolated test environment)

### Setup Attempts: ⚠️ Complex
**What worked:**
- ✅ Memory system initialized (`ruflo memory init`)
- ✅ Daemon started (`ruflo daemon start`)
- ✅ Task created (`ruflo task create`)
- ✅ Swarm initialized (`ruflo swarm init --topology hierarchical`)
- ✅ Task assigned (`ruflo task assign`)

**What didn't work:**
- ❌ Task execution failed (no actual code modification)
- ❌ Token usage measurement (couldn't extract metrics)
- ❌ Agent Booster WASM (not accessible as standalone CLI)
- ❌ Real performance testing (requires full provider configuration)

**Time spent:** 45 minutes  
**Actual tests completed:** 0

### Complexity Issues

**Ruflo requires extensive setup:**
1. Daemon initialization
2. Memory system configuration
3. Swarm topology setup
4. Provider API keys (Anthropic, OpenAI, etc.)
5. Task creation + assignment workflow
6. Understanding agent execution lifecycle
7. Debugging task failures

**Not a simple drop-in optimization** — it's a full orchestration platform replacement.

---

## Token Reduction Claims: Unverified

### Simulated Results (Not Real)
Initial "test" script generated **simulated data** based on Ruflo's published claims:
- Simple tasks: 100% savings (WASM)
- Medium tasks: 62.5% savings (Haiku routing)
- Complex tasks: 0% savings (same Opus)
- **Overall: 18.8% savings** (based on 33% simple/medium, 67% complex workload)

**These numbers were NOT from real testing** — they were extrapolations from Ruflo's documentation.

### Real Testing: Blocked
Could not validate claims because:
- Task execution workflow too complex to complete in evaluation window
- No clear path to extract token usage metrics
- Provider configuration required but not completed

---

## Why We Rejected Ruflo

### 1. **Setup Complexity vs Benefit**
- 45 minutes invested, 0 tests completed
- Integration would take days/weeks of work
- Uncertain ROI for OpenClaw's use case

### 2. **Workload Mismatch**
OpenClaw's real usage is mostly **complex tasks** (architecture, features, refactoring):
- Agent Booster WASM: saves 100% on simple tasks (but those are rare)
- 3-tier routing: saves 0% on complex tasks (where most work happens)
- Even if claims are true, blended savings would be 15-25% (not 30-50%)

### 3. **Integration Cost**
Ruflo is a **framework replacement**, not a plugin:
- Own daemon, swarm manager, task lifecycle
- Conflicts with OpenClaw's sessions_spawn architecture
- AgentDB memory vs MEMORY.md fragmentation risk
- MCP server conflicts (both want to orchestrate)

### 4. **Disk + Memory Footprint**
- 65MB install (minimal) or 340MB (full)
- Runtime daemon + workers + swarm state
- OpenClaw is deliberately lean — Ruflo is enterprise-grade heavy

### 5. **No Clear Win on Complex Tasks**
Ruflo's 3-tier routing:
- Simple → WASM (great, but rare)
- Medium → Haiku (good, but OpenClaw already can do this)
- Complex → Opus (same as OpenClaw, no savings)

**Most real software work is complex.** Token savings on simple tasks don't move the needle.

---

## What We Learned

### Valid Concepts Worth Keeping
1. **3-tier routing logic** — Task complexity → model selection is smart
2. **WASM for simple transforms** — Skip LLM for formatting/linting makes sense
3. **Agent specialization** — Right agent for right task improves quality

### Implementation Without Ruflo
OpenClaw can adopt these concepts without the framework:

```javascript
// Simple routing logic (no Ruflo needed)
function selectModel(task) {
  const complexity = analyzeTaskComplexity(task);
  
  if (complexity === 'simple' && isFormatting(task)) {
    return 'haiku'; // or local formatter
  } else if (complexity === 'medium') {
    return 'haiku';
  } else {
    return 'opus'; // complex tasks need the power
  }
}
```

### Better Optimizations for OpenClaw
Instead of Ruflo integration:
1. **Break complex tasks into medium chunks** — more Haiku, less Opus
2. **Use Haiku for first pass** — Opus only for final review
3. **Local tools for simple transforms** — eslint, prettier, sed (0 tokens)
4. **Batch similar tasks** — reuse context across related work

---

## Final Verdict

**Ruflo is impressive technology, but wrong fit for OpenClaw.**

**Reasons:**
- ❌ Too complex for uncertain benefit
- ❌ Framework replacement, not optimization
- ❌ Workload mismatch (complex tasks dominate)
- ❌ Integration cost exceeds value
- ❌ 45 min evaluation → 0 working tests

**Alternative:**
- ✅ Keep OpenClaw's lean architecture
- ✅ Manually implement 3-tier routing concept
- ✅ Use Haiku more aggressively for medium tasks
- ✅ Optimize task breakdown strategy

**Decision:** Cleaned up test environment (freed 65MB), documented findings for future reference.

---

## References

- **Ruflo repo:** https://github.com/ruvnet/ruflo
- **Claimed benchmarks:** 352x speedup (WASM), 30-50% token savings
- **Install command:** `npm install ruflo@latest --omit=optional`
- **Our test environment:** `~/.openclaw-ruflo/` (deleted Mar 23 23:57 MST)

---

**Researched:** 2026-03-23 18:08 MST (initial)  
**Evaluated:** 2026-03-23 21:55-23:57 MST (hands-on testing)  
**Decision:** Rejected (complexity exceeds value)  
**By:** Jarvis COO

# Ruflo Research — March 23, 2026

**Repo:** https://github.com/ruvnet/ruflo  
**Status:** Active, production-ready v3.5  
**For:** Claude Code multi-agent orchestration

---

## What Is Ruflo?

**"Enterprise AI Orchestration Platform"** — A self-learning agent framework that transforms Claude Code into a multi-agent development system.

**Key tagline:** *Deploy 60+ specialized agents in coordinated swarms with self-learning capabilities, fault-tolerant consensus, and enterprise-grade security.*

---

## Core Capabilities

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

### ⚡ Performance Optimization
- **Agent Booster (WASM)** — simple code transforms skip LLM entirely (<1ms vs 2-5s)
- **3-tier model routing** — simple tasks → free WASM, medium → Haiku, complex → Opus
- **Token optimizer** — 30-50% token reduction via compression + caching
- **Cost savings** — 75% lower API costs, 2.5x Claude Max extension

### 🔌 Integration
- **MCP native** — 259 tools for Claude Code, VS Code, Cursor, Windsurf
- **Multi-provider** — Anthropic, OpenAI, Google, Ollama with failover
- **42+ skills** — pre-built capabilities for coding, security, testing, DevOps
- **OpenAI Codex support** — dual-mode with Claude Code

---

## Relevance to OpenClaw?

### Potential Synergies

| OpenClaw Feature | Ruflo Capability | Potential Benefit |
|------------------|------------------|-------------------|
| **Subagent delegation** | Swarm coordination with consensus | Better multi-agent orchestration for complex tasks |
| **Builder spawning** | Queen-led hierarchy + 60+ agent types | Pre-built specialized agents instead of generic builders |
| **Token management** | 3-tier routing + Agent Booster (WASM) | 75% cost reduction, 2.5x quota extension |
| **Memory/context** | HNSW vector search + knowledge graph | Fast pattern retrieval, influence-aware insights |
| **Domain agents** | MoE expert routing | Intelligent task routing based on learned patterns |
| **Status tracking** | Persistent AgentDB memory | Cross-session context preservation |

### Key Questions

1. **Architecture overlap** — OpenClaw already has sessions_spawn, sessions_send, subagents. Does Ruflo's swarm coordination add value or just complexity?

2. **Memory integration** — OpenClaw uses MEMORY.md + daily logs. Ruflo has vector DB + knowledge graphs. Can they coexist or would it fragment memory?

3. **Model routing** — OpenClaw uses Opus for main, Nemotron for builders, Haiku for crons. Ruflo's 3-tier routing could optimize this further.

4. **MCP overlap** — OpenClaw already IS an MCP server. Ruflo is also an MCP server. Would they conflict or complement?

5. **Complexity vs benefit** — Ruflo is a heavy framework (340MB install, 259 MCP tools). Is the learning/coordination worth the added complexity?

### Immediate Value Props

✅ **Agent Booster (WASM)** — instant simple transforms without LLM calls (352x faster)
✅ **Vector memory** — HNSW search for pattern retrieval (150x faster than linear)
✅ **Cost optimization** — 3-tier routing could reduce token usage 30-50%
✅ **Swarm topologies** — hierarchical coordination for multi-agent tasks
✅ **Self-learning** — system improves from experience

⚠️ **Potential Issues:**
- Heavy dependency footprint (340MB vs OpenClaw's lean design)
- Another layer of abstraction over sessions_spawn
- Memory fragmentation (MEMORY.md vs AgentDB)
- MCP server conflicts (both want to be THE orchestrator)

---

## Recommendation

### Evaluation Path

1. **Install & test** — `npx ruflo@latest init` in a test workspace
2. **Run Agent Booster demo** — measure WASM transform speed vs LLM
3. **Test swarm coordination** — spawn 4-8 agents on a complex task, compare to OpenClaw's sessions_spawn
4. **Check MCP integration** — can Ruflo MCP server coexist with OpenClaw's gateway?
5. **Memory compatibility** — does AgentDB play nice with MEMORY.md or fragment context?

### If Evaluation Passes

**Selective adoption:**
- Use Agent Booster for simple transforms (proven 352x speedup)
- Adopt 3-tier routing logic (not the full framework)
- Integrate HNSW vector search for pattern retrieval
- Keep OpenClaw's core orchestration (sessions_spawn, agents, crons)

**Avoid:**
- Full Ruflo replacement (too heavy, architectural mismatch)
- Dual MCP servers (conflict risk)
- AgentDB as primary memory (stick with MEMORY.md + daily logs)

---

## Technical Details

**Installation:**
```bash
# One-line install
curl -fsSL https://cdn.jsdelivr.net/gh/ruvnet/claude-flow@main/scripts/install.sh | bash

# Or via npx
npx ruflo@latest init --wizard
```

**MCP integration:**
```bash
# Add to Claude Code
claude mcp add ruflo -- npx -y ruflo@latest mcp start
```

**Agent Booster example:**
```bash
# Simple transform (skips LLM)
ruflo edit --intent var-to-const --file src/index.js
# Result: <1ms vs 2-5s LLM call
```

---

## Conclusion

**Ruflo is a sophisticated multi-agent framework with proven cost/speed optimizations.**

**Best fit for OpenClaw:**
- Evaluate Agent Booster WASM transforms (clear 352x win)
- Consider 3-tier routing logic for token savings
- Test swarm coordination for complex multi-agent tasks
- **Do NOT replace OpenClaw's core** — it's already lean and working

**Next step:** Practical evaluation in a sandbox workspace to measure real benefit vs added complexity.

---

**Researched:** 2026-03-23 18:08 MST  
**By:** Jarvis COO  
**Updated:** 2026-03-23 18:10 MST (full findings)

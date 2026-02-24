# Claude Code Agent Teams — Quick Reference

## What It Is
Multiple Claude Code instances working in parallel on the same codebase. One lead agent coordinates, teammates work independently in their own context windows and can message each other directly.

## When to Use
- Parallel feature development (each teammate owns a module)
- Research & review from multiple angles
- Debugging with competing hypotheses
- Cross-layer changes (frontend + backend + tests)
- **Large refactors like the Blofin pipeline redesign**

## When NOT to Use
- Sequential tasks with dependencies
- Same-file edits (conflicts)
- Simple one-off changes (overkill)

## Setup
Already enabled on omen-claw:
```json
// ~/.claude/settings.json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

## How to Launch from OpenClaw (Jarvis)

### Interactive mode (recommended for Agent Teams):
```bash
exec pty:true background:true workdir:~/project timeout:7200 command:"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 claude --dangerously-skip-permissions --teammate-mode in-process"
```

Then paste the task via `process action:paste` with `bracketed:true`, then `send-keys Enter`.

### Permissions prompt
Claude Code shows a bypass permissions warning. Navigate with:
1. Send key `2` (select "Yes, I accept")
2. Send `Enter`

**Watch out:** Default selection is "No, exit" — must explicitly select option 2.

### Monitoring
- Teammates show as subagent `.jsonl` files under `~/.claude/projects/<project>/<session-id>/subagents/`
- Check teammate count: `find ~/.claude/projects/*/<session>/subagents/ -name "*.jsonl" | wc -l`
- Read teammate progress: `tail -1 <subagent.jsonl> | python3 -c "import json,sys; ..."`
- Process count: `ps aux | grep claude | grep -v grep | wc -l`
- Title bar shows task name (e.g., "Agent Team Deployment")

### Task Prompt Pattern
Tell the lead what teammates to create and what each should do:
```
Create an agent team with N teammates. Use Sonnet for each teammate.
Teammate 1 (Name): [specific task]
Teammate 2 (Name): [specific task]
...
Require plan approval before teammates make changes.
```

## vs OpenClaw Subagents

| | Agent Teams | OpenClaw sessions_spawn |
|---|---|---|
| Communication | Teammates message each other | Report back to parent only |
| Context | Own context window, sees codebase | Own context, sees codebase |
| Coordination | Shared task list, self-coordinate | Independent, no cross-talk |
| Best for | Complex multi-file code changes | Focused single tasks |
| Token cost | Higher (parallel contexts) | Lower (results summarized) |
| Monitoring | .jsonl files + process log | sessions_list + sessions_history |

## Key Lessons (Feb 18, 2026)
- `-p` (print) flag does NOT support Agent Teams — must use interactive mode
- Teammates spawn as in-process subagents (not separate OS processes)
- Lead agent reads plan, creates teammates, approves their plans before execution
- Plan approval mode is good for complex work — prevents teammates from going rogue
- 4 teammates is a good sweet spot for a major refactor
- Teammates can work on: ML pipeline, strategy files, systemd timers, dashboard — all in parallel without conflicts if scoped to different directories

## Real-World Comparison: Agent Teams vs OpenClaw Subagents

### Test Case: Blofin Pipeline Redesign (Feb 18, 2026)
**Scope:** 4 tasks — ML leakage fix, strategy lifecycle, pipeline scheduling, dashboard rebuild

#### Agent Teams (what we used)
- **Session 1 (tide-summit):** 3/4 tasks completed before rate limit hit (~45 min)
- **Session 2 (rapid-prairie):** Task 4 completed in ~9 minutes
- **Total wall-clock:** ~55 minutes for all 4 tasks
- **Quality:** All code committed, tested, no rework needed
- **Coordination:** Teammates auto-coordinated on shared DB schema, no conflicts
- **Downside:** Rate limits hit harder because 4 parallel contexts burn tokens fast. One session wasn't enough — needed a second.

#### OpenClaw Subagents (typical pattern)
- 4 independent `sessions_spawn` calls with `model=sonnet`
- Each gets a focused task prompt, reports back
- **Estimated wall-clock:** 30-40 min (similar parallelism)
- **Coordination:** None between subagents. Jarvis must manually resolve conflicts.
- **Token cost:** Lower per-agent (summarized results), but Jarvis review adds overhead
- **Quality:** More variable — each subagent works in isolation, may make conflicting assumptions

#### Verdict
| Factor | Agent Teams | OpenClaw Subagents |
|--------|------------|-------------------|
| **Speed** | ★★★★ Fast parallel | ★★★★ Similar parallel |
| **Coordination** | ★★★★★ Auto cross-talk | ★★ Manual via Jarvis |
| **Token efficiency** | ★★ Burns tokens fast | ★★★★ Leaner per-task |
| **Rate limit risk** | ★★ Hit limits on Session 1 | ★★★★ Spread across models |
| **Quality control** | ★★★★ Self-reviewing | ★★★ Needs Jarvis review |
| **Setup complexity** | ★★★ PTY + paste dance | ★★★★★ Simple API call |
| **Best for** | Multi-file refactors in ONE repo | Independent focused tasks |

#### TL;DR
- **Agent Teams** when: 3+ tasks touch the same codebase and need to know about each other's changes (shared schemas, imports, configs). Worth the token cost for coordination.
- **OpenClaw Subagents** when: Tasks are independent (different repos, different concerns), or you want to mix models (Sonnet for code, Mini for automation). Cheaper and simpler.
- **Don't use Agent Teams for:** Sequential work, single-file fixes, cross-repo tasks, or anything where you'd just be spawning 1 teammate (pointless overhead).

#### Cost Reality
On Claude Max 5x ($100/mo flat), Agent Teams are "free" — no marginal cost. The only cost is burning through your 5-hour usage cap faster. A 4-teammate session used roughly 3x the tokens of a single-agent equivalent. If you're rate-limited, that matters. If you have headroom, it's the better tool for complex refactors.

# CONTEXT.md - Jarvis Boot File

**Read this first if you're starting from Claude Code CLI (fallback mode).**

## Where Everything Lives

| What | Path |
|------|------|
| Jarvis brain | `~/.openclaw/workspace/brain/` |
| Live status | `~/.openclaw/workspace/brain/status/status.json` |
| Code standards | `~/.openclaw/workspace/brain/STANDARDS.md` |
| Persona files | `~/.openclaw/workspace/SOUL.md`, `USER.md`, `IDENTITY.md`, `AGENTS.md` |
| Workspace | `~/.openclaw/workspace/` |
| OpenClaw config | `~/.openclaw/openclaw.json` |
| Auth profiles | `~/.openclaw/agents/main/agent/auth-profiles.json` |
| Gateway service | `systemctl --user status openclaw-gateway.service` |
| Incident log | `~/.claude/projects/-home-rob/memory/incidents.md` |

## Active Projects & Services

| Project | Path | Repo | Service |
|---------|------|------|---------|
| Blofin Pipeline | `~/.openclaw/workspace/blofin-stack/` | github.com/robbyrobaz/blofin-trading-pipeline | blofin-stack-ingestor, blofin-stack-api, blofin-stack-paper |
| Blofin Dashboard | `~/.openclaw/workspace/blofin-dashboard/` | — | blofin-dashboard.service |
| AI Workshop | `~/.openclaw/workspace/ai-workshop/` | github.com/robbyrobaz/ai-workshop | — |

## Common Fixes

### OpenClaw gateway down
```bash
systemctl --user restart openclaw-gateway.service
journalctl --user -u openclaw-gateway.service --since "5 min ago" --no-pager | tail -20
```

### Rate limit cooldown (all models failing)
```bash
systemctl --user stop openclaw-gateway.service
# Edit ~/.openclaw/agents/main/agent/auth-profiles.json
# Reset usageStats: set errorCount to 0, remove cooldownUntil and failureCounts
systemctl --user start openclaw-gateway.service
```

### Service health check
```bash
systemctl --user list-units --all --state=failed
systemctl --user list-timers --all
```

## How to Resume Work

1. Read `~/.openclaw/workspace/brain/status/status.json` — see what's in progress
2. Read `~/.openclaw/workspace/SOUL.md` — remember who you are
3. Read `~/.openclaw/workspace/brain/CONTEXT.md` — this file
4. Pick up where you left off

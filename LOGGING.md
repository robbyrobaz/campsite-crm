# Logging Standards Quick Reference

## Script Spawning Template

```python
# Create logs dir
exec(command="mkdir -p logs", workdir="/path/to/repo")

# Spawn with logging
exec(
    command="python scripts/my_script.py 2>&1 | tee logs/my-script-$(date +%s).log",
    background=True,
    workdir="/path/to/repo",
    timeout=3600
)
```

## Progress Format

```
[TIMESTAMP] [STAGE] message
```

**Stages:** `[INIT]` `[PROGRESS]` `[ERROR]` `[FATAL]` `[COMPLETE]` `[SUMMARY]`

**Example:**
```
[2026-03-22 14:00:00] [INIT] Starting backtest sweep for 500 strategies
[2026-03-22 14:05:00] [PROGRESS] 100/500 (20%, ETA 20min)
[2026-03-22 14:25:00] [COMPLETE] All 500 strategies processed
```

## Log Locations

- **OpenClaw sessions:** `~/.openclaw/agents/{agent}/sessions/{id}.jsonl` (automatic)
- **Scripts:** `~/.openclaw/workspace/logs/{script}-{timestamp}.log` (use `tee`)
- **Services:** `journalctl --user -u {service}.service -f`

## Dashboard Viewing

1. Open: `http://127.0.0.1:8080`
2. Go to "Live Agent Work"
3. Click any session/process → log streams live

See `docs/AGENT_SUBAGENT_MONITORING.md` for full guide.

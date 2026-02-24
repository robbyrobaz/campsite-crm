# Runbook: Blofin 24/7 Pattern Stack

## Architecture
1. **Ingestion**: Blofin public websocket (`tickers`) for 25 symbols
2. **Storage**: SQLite (`blofin-research/data/blofin.db`) tables:
   - `ticks` (raw normalized price points)
   - `signals` (pattern-derived BUY/SELL)
3. **Pattern engine** (real-time):
   - momentum up/down over rolling window
   - breakout/breakdown over lookback
   - reversal from local peak/trough
4. **Dashboards**:
   - Blofin metrics/signals dashboard
   - Ops kanban dashboard

## Services (systemd user)
- `blofin-research.service`
- `blofin-dashboard.service`
- `ops-kanban-dashboard.service`
- `openclaw-full-restore-backup.timer`

## Dashboard URLs (local)
- Blofin Dashboard: `http://127.0.0.1:8766`
- Blofin Metrics API: `http://127.0.0.1:8766/api/metrics`
- Ops Kanban Dashboard: `http://127.0.0.1:8767`

## Startup / restart
```bash
systemctl --user daemon-reload
systemctl --user restart blofin-research.service blofin-dashboard.service ops-kanban-dashboard.service
systemctl --user status blofin-research.service blofin-dashboard.service ops-kanban-dashboard.service --no-pager
```

## Logs
```bash
journalctl --user -u blofin-research.service -f
journalctl --user -u blofin-dashboard.service -f
```

## DB quick checks
```bash
sqlite3 /home/rob/.openclaw/workspace/blofin-research/data/blofin.db 'select count(*) from ticks;'
sqlite3 /home/rob/.openclaw/workspace/blofin-research/data/blofin.db 'select count(*) from signals;'
sqlite3 /home/rob/.openclaw/workspace/blofin-research/data/blofin.db 'select symbol, count(*) c from ticks group by symbol order by c desc limit 10;'
```

## Tuning
Edit `/home/rob/.openclaw/workspace/blofin-research/.env`:
- `WINDOW_SECONDS`
- `MOMENTUM_PCT`
- `REVERSAL_PCT`
- `BREAKOUT_LOOKBACK`
- token list in `BLOFIN_SYMBOLS`

## Week-long monitoring objective
- Keep service running 24/7
- Review `/api/metrics` daily for signal density and pattern quality
- After ~7 days, refine thresholds based on observed false positives

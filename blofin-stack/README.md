# Blofin Monitoring Stack (Restored + Ops Kanban)

Local-first monitoring stack for Blofin public market data:

- WebSocket ingestion for ~25 symbols
- Durable SQLite storage (`ticks`, `signals`, `service_heartbeats`, `kanban_*`)
- Pattern detectors (momentum + breakout + reversal)
- Buy/sell signal recording
- Local dashboard/API endpoints
- Integrated ops kanban board with worker auto-pick
- systemd user services for auto-start

## Quick start

```bash
cd /home/rob/.openclaw/workspace/blofin-stack
cp .env.example .env
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python ingestor.py
# in another terminal:
python api_server.py
# optional third terminal:
python kanban_worker.py
```

## API

- `GET /healthz`
- `GET /api/summary`
- `GET /api/timeseries?symbol=BTC-USDT&limit=300`
- `GET /api/gap-fills`
- `GET /api/kanban/tasks`
- `POST /api/kanban/tasks`
- `POST /api/kanban/move`
- `POST /api/kanban/approve`
- `POST /api/kanban/reject`
- `GET /` (HTML dashboard + kanban panel)

## Kanban auto-pick priority

`kanban_worker.py` auto-moves tasks from `inbox` to `in_progress` while there is capacity.

Selection order:
1. Higher `priority` first (`5` highest in current worker sort)
2. Older `created_ts_ms` first
3. Lower `id` first (stable tie-break)

Capacity is controlled by `KANBAN_MAX_IN_PROGRESS` and loop frequency by `KANBAN_WORKER_LOOP_SECONDS`.

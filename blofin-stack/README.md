# Blofin Monitoring Stack (Restored)

Local-first monitoring stack for Blofin public market data:

- WebSocket ingestion for ~25 symbols
- Durable SQLite storage (`ticks`, `signals`, `service_heartbeats`)
- Pattern detectors (momentum + breakout + reversal)
- Buy/sell signal recording
- Local dashboard/API endpoints
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
```

## API

- `GET /healthz`
- `GET /api/summary`
- `GET /api/signals?limit=100`
- `GET /api/ticks/latest?limit=100`
- `GET /` (HTML dashboard)

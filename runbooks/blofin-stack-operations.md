# Runbook: Blofin Monitoring Stack Operations

## Components
- Ingestor service: `blofin-stack-ingestor.service`
- API/dashboard service: `blofin-stack-api.service`
- Gap-fill timer: `blofin-stack-gapfill.timer` (+ `blofin-stack-gapfill.service`)
- DB: `/home/rob/.openclaw/workspace/blofin-stack/data/blofin_monitor.db`
- **Single dashboard**: `http://127.0.0.1:8780/`

## Install / Reinstall
```bash
cd /home/rob/.openclaw/workspace
chmod +x scripts/install-blofin-stack-services.sh scripts/install-blofin-stack-gapfill.sh
./scripts/install-blofin-stack-services.sh
./scripts/install-blofin-stack-gapfill.sh
```

## Verify health
```bash
systemctl --user status blofin-stack-ingestor.service --no-pager
systemctl --user status blofin-stack-api.service --no-pager
journalctl --user -u blofin-stack-ingestor.service -n 100 --no-pager
curl -sS http://127.0.0.1:8780/healthz
curl -sS http://127.0.0.1:8780/api/summary | head
```

## Common operations
```bash
systemctl --user restart blofin-stack-ingestor.service
systemctl --user restart blofin-stack-api.service
systemctl --user restart dashboard-health-check.service
systemctl --user stop blofin-stack-ingestor.service blofin-stack-api.service
systemctl --user start blofin-stack-ingestor.service blofin-stack-api.service
```

## Auto-start on login
Both services are `enable`d to `default.target`. For start before interactive login:
```bash
sudo loginctl enable-linger rob
```

## Tuning
Edit `/home/rob/.openclaw/workspace/blofin-stack/.env`:
- `BLOFIN_SYMBOLS` (~25 tokens default)
- `MOMENTUM_*`, `BREAKOUT_*`, `REVERSAL_*`
- `SIGNAL_COOLDOWN_SECONDS`
- `API_PORT`

# Blofin Repo Audit (2026-02-11 MST)

## Repos inspected
- `ML_Predict_Assets` (origin: `robbyrobaz/ML_Predict_Assets`)
- `tradingview-triggers-1` (origin: `robbyrobaz/tradingview-triggers-1`)
- `cloud-code-function-tradingview-triggers-bOvuLu` (origin: `robbyrobaz/cloud-code-function-tradingview-triggers-bOvuLu`)
- `BTC` (origin: `robbyrobaz/BTC`)
- workspace stack (`blofin-stack`, `systemd`, `scripts`, `runbooks`)

## Findings
1. Existing legacy trigger repos are minimal and not a durable monitoring platform.
2. `tradingview-triggers-1/process.env` contains hardcoded secret material and must not be committed or reused.
3. Restored stack in workspace is local-first and production-friendly for monitoring:
   - websocket ingestion (~25 symbols)
   - sqlite durability
   - momentum + breakout + reversal heuristics
   - buy/sell signal persistence
   - local dashboard/API
   - user-level systemd auto-start + runbooks

## Operational endpoints
- Dashboard: `http://127.0.0.1:8780/`
- Health: `http://127.0.0.1:8780/healthz`
- Summary: `http://127.0.0.1:8780/api/summary`
- Signals: `http://127.0.0.1:8780/api/signals?limit=100`
- Ticks: `http://127.0.0.1:8780/api/ticks/latest?limit=100`

## systemd services
- `blofin-stack-ingestor.service`
- `blofin-stack-api.service`

Install/start:
```bash
cd /home/rob/.openclaw/workspace
./scripts/install-blofin-stack-services.sh
```

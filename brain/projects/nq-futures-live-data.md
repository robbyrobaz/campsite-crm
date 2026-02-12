# NQ Futures Live Data (CME) — practical options for this laptop/OpenClaw

Last updated: 2026-02-11

## Goal
Get **live Nasdaq-100 futures (NQ/MNQ)** data in a way that is realistic for a retail setup, compliant with exchange terms, and usable from this Linux/OpenClaw environment.

---

## Short comparison

| Option | CME/NinjaTrader fit | API access | Typical cost notes* | Latency notes | Legal/terms notes |
|---|---|---|---|---|---|
| **Databento (GLBX.MDP3)** | CME-native (not a NinjaTrader broker feed) | Python/HTTP + live streaming | Usage-based vendor billing + CME entitlement pass-through (light use often low tens/month; heavy tick capture scales with usage) | Very good for software ingestion; lower latency than retail broker APIs in many setups | Exchange entitlements required; non-display + redistribution restrictions apply |
| **Tradovate API (NinjaTrader ecosystem)** | Strong NinjaTrader ecosystem fit | REST + WebSocket | Brokerage plan + exchange/NFA/clearing fees; market data requires CME entitlements | Good retail latency; internet + broker infra dependent | Account + exchange agreements required; generally personal/non-redistribution unless licensed |
| **NinjaTrader Desktop via CQG/Rithmic** | Best direct NinjaTrader platform fit | Programmatic access mainly via NinjaScript/C# add-ons (Windows-centric) | Platform/broker plan + exchange data fees (commonly low single-digit to teens per exchange/bundle for non-pro) | Strong for discretionary and platform-embedded automation | Must honor exchange/professional classification and vendor licensing |
| **IBKR TWS/Gateway API** | CME-supported (not NinjaTrader-native feed) | Stable API (Python via ib_insync) | Subscriptions (e.g., bundles starting around ~$10/mo; extra exchange subscriptions possible) | Adequate for many algos; generally slower than direct-feed vendors | Personal use only unless licensed; API market data tied to subscriber permissions |

\*Costs vary by account type (professional vs non-professional), region, and current exchange schedules. Always verify at account checkout pages before implementation.

---

## Recommended v1 path (for **this Linux laptop + OpenClaw**)

## **Recommendation: Databento GLBX.MDP3 live feed**

Why this is the best v1 here:
1. **Linux-first and scriptable** (no Windows/NinjaTrader desktop dependency).
2. **Fast path to value**: Python script can stream NQ trades/quotes immediately.
3. **Clean architecture for OpenClaw**: run one collector process, write normalized JSONL/CSV/Parquet, reuse for research/alerts.
4. **CME-native symbology** with clear contract handling for front-month roll logic.

If your primary objective becomes order execution in NinjaTrader specifically, add a phase-2 bridge (Tradovate/NinjaTrader account-side integration) while keeping this data pipeline as independent market-data infrastructure.

---

## Implementation checklist (exact commands)

### 0) Workspace
```bash
cd /home/rob/.openclaw/workspace
mkdir -p market-data/nq/{scripts,data,logs}
```

### 1) Python env
```bash
cd /home/rob/.openclaw/workspace/market-data/nq
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install databento python-dotenv
```

### 2) Secrets
Create `.env`:
```bash
cat > /home/rob/.openclaw/workspace/market-data/nq/.env << 'EOF'
DATABENTO_API_KEY=REPLACE_ME
# Optional explicit symbol; keep as configured in script if omitted
NQ_SYMBOL=NQ
EOF
```

### 3) Minimal live collector script
```bash
cat > /home/rob/.openclaw/workspace/market-data/nq/scripts/stream_nq.py << 'EOF'
#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import databento as db
from dotenv import load_dotenv

load_dotenv('/home/rob/.openclaw/workspace/market-data/nq/.env')
api_key = os.environ['DATABENTO_API_KEY']

out_dir = Path('/home/rob/.openclaw/workspace/market-data/nq/data')
out_dir.mkdir(parents=True, exist_ok=True)
out_file = out_dir / f"nq_live_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"

# Dataset/symbol mapping can change; verify current Databento symbology in account docs.
# Use front-month continuous logic in production.
DATASET = 'GLBX.MDP3'
SCHEMA = 'trades'  # change to 'mbp-1' for top-of-book
SYMBOLS = ['NQ.FUT']

live = db.Live(key=api_key)
live.subscribe(dataset=DATASET, schema=SCHEMA, symbols=SYMBOLS)

print(f"Streaming {SYMBOLS} -> {out_file}")
with out_file.open('a', encoding='utf-8') as f:
    for rec in live:
        row = {
            'ts_recv': getattr(rec, 'ts_recv', None),
            'ts_event': getattr(rec, 'ts_event', None),
            'price': getattr(rec, 'price', None),
            'size': getattr(rec, 'size', None),
            'symbol': getattr(rec, 'symbol', None),
        }
        f.write(json.dumps(row, default=str) + '\n')
        f.flush()
EOF
chmod +x /home/rob/.openclaw/workspace/market-data/nq/scripts/stream_nq.py
```

### 4) Run collector
```bash
cd /home/rob/.openclaw/workspace/market-data/nq
source .venv/bin/activate
python scripts/stream_nq.py
```

### 5) Operationalize (systemd user service)
```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/nq-live.service << 'EOF'
[Unit]
Description=NQ live data collector (Databento)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/rob/.openclaw/workspace/market-data/nq
EnvironmentFile=/home/rob/.openclaw/workspace/market-data/nq/.env
ExecStart=/home/rob/.openclaw/workspace/market-data/nq/.venv/bin/python /home/rob/.openclaw/workspace/market-data/nq/scripts/stream_nq.py
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now nq-live.service
systemctl --user status nq-live.service --no-pager
journalctl --user -u nq-live.service -f
```

---

## Compliance/terms checklist (don’t skip)

- [ ] Confirm **non-professional vs professional** status correctly.
- [ ] Purchase proper **CME market data entitlements** for live futures.
- [ ] Use data for **personal/internal** use unless redistribution rights are explicitly licensed.
- [ ] If using data in automation/backtesting infra, verify whether usage is considered **non-display** under your vendor/exchange terms.
- [ ] Keep API keys local (`.env`, not committed).

---

## Source pointers to verify current pricing/terms

- Databento pricing and docs: https://databento.com/pricing and docs portal
- IBKR market data pricing overview: https://www.interactivebrokers.com/en/pricing/market-data-pricing.php
- Tradovate/NinjaTrader ecosystem pricing and exchange-fee caveats: https://www.tradovate.com/ (pricing + FAQs)

(Cloudflare and dynamic pages may block automated fetch; verify final fees in-account before subscribing.)

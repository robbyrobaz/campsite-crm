# IBKR Setup Research - Ubuntu Linux Data Pipeline

**Date:** 2026-02-28  
**Status:** Research Complete  
**Goal:** Stable, OpenClaw-managed IBKR connection for options data streaming (SPX 0DTE + stock options)

---

## Executive Summary

**Recommended Stack:**
- **IB Gateway:** Docker container `ghcr.io/gnzsnz/ib-gateway:stable` (v10.37.1o)
- **Python Client:** `ib_async` (v2.1.0) — actively maintained fork of ib_insync
- **Session Management:** IBC 3.23.0 (bundled in Docker image)
- **Bot Runtime:** Native Python via systemd user service

**Why This Stack:**
1. Docker isolates Java/Xvfb complexity — no virtual display headaches
2. IBC handles auto-login, 2FA timeout recovery, and daily auto-restart
3. `ib_async` is the modern, maintained successor to `ib_insync`
4. Native Python bot is simpler to debug and integrates with existing OpenClaw services

---

## 1. Which IBKR Software to Run on Ubuntu?

### Option Analysis

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **TWS (GUI)** | Full featured, most docs | Heavy (1GB+ RAM), requires Xvfb, login headaches | ❌ Overkill for API-only |
| **IB Gateway (native)** | Lighter than TWS, designed for automation | Still needs Xvfb, manual IBC setup | ⚠️ Works but more setup |
| **IB Gateway (Docker)** | Clean isolation, auto-login, auto-restart, VNC for debugging | Docker dependency | ✅ **Winner** |

### Winner: Docker Container (`ghcr.io/gnzsnz/ib-gateway:stable`)

**Reasons:**
1. **Handles Xvfb internally** — IB Gateway requires X11 even in "headless" mode. Docker abstracts this.
2. **IBC bundled** — Auto-login, 2FA handling, session management included
3. **Auto-restart on 24h timeout** — Set `AUTO_RESTART_TIME=11:59 PM` and forget
4. **VNC debugging** — Connect to port 5900 to see what IB Gateway is showing
5. **Compose-managed** — OpenClaw can manage via `docker compose` or systemd
6. **Parallel paper/live** — Can run both trading modes simultaneously

**Image Tags:**
- `ghcr.io/gnzsnz/ib-gateway:stable` — v10.37.1o (recommended for production)
- `ghcr.io/gnzsnz/ib-gateway:latest` — v10.44.1f (weekly updates, bleeding edge)
- `ghcr.io/gnzsnz/ib-gateway:10.37` — Pinned to major version

**Use stable tag** — latest can introduce breaking changes.

---

## 2. Authentication & Session Management

### The 24-Hour Logout Problem

IBKR enforces a daily session timeout. Every ~24 hours, IB Gateway/TWS disconnects. This is non-negotiable — it's a security requirement.

### How Docker + IBC Solves It

IBC (Interactive Brokers Controller) is the key component:

1. **Auto-login** — Fills username/password on startup
2. **2FA handling** — If using IBKR Mobile 2FA, IBC waits for approval with configurable timeout
3. **Auto-restart** — `AUTO_RESTART_TIME=11:59 PM` restarts daily WITHOUT requiring new 2FA
4. **Session conflict resolution** — `EXISTING_SESSION_DETECTED_ACTION=primary` takes over existing sessions

**Key Environment Variables:**
```bash
TWS_USERID=your_username
TWS_PASSWORD=your_password
TRADING_MODE=paper              # or "live" or "both"
AUTO_RESTART_TIME=11:59 PM      # Daily restart WITHOUT new 2FA
TWOFA_TIMEOUT_ACTION=restart    # On 2FA timeout: restart (not exit)
RELOGIN_AFTER_TWOFA_TIMEOUT=yes # Keep trying after 2FA fails
EXISTING_SESSION_DETECTED_ACTION=primary  # Take over existing sessions
```

### 2FA Considerations

**Option A: Disable 2FA for API (recommended for automation)**
- In IBKR Account Management → Security → enable "Allow API connections without 2FA"
- You lose some account protection guarantees
- This is what most algo traders do

**Option B: Keep 2FA, handle timeouts**
- `TWOFA_TIMEOUT_ACTION=restart` + `RELOGIN_AFTER_TWOFA_TIMEOUT=yes`
- IBC will retry login every `TWOFA_EXIT_INTERVAL` seconds (default 60)
- You get alerts on your phone when it needs auth
- More secure but requires occasional manual intervention

### Credential Storage Best Practices

**For Ubuntu server:**

1. **Environment file (recommended)**
   ```bash
   # /home/rob/.ibkr/credentials.env
   TWS_USERID=your_username
   TWS_PASSWORD=your_password
   VNC_SERVER_PASSWORD=your_vnc_password
   ```
   - Permissions: `chmod 600 ~/.ibkr/credentials.env`
   - Reference in docker-compose: `env_file: ~/.ibkr/credentials.env`

2. **Docker secrets (more secure)**
   - Create password file: `echo "your_password" > /run/secrets/ibkr_password`
   - Use `TWS_PASSWORD_FILE=/run/secrets/ibkr_password`
   - Mount as secret in compose

**Never commit credentials to git.**

### What Happens to Python Bot on Disconnect?

When IB Gateway disconnects:
1. `ib_async` fires a `disconnectedEvent`
2. Active market data subscriptions are lost
3. Pending requests fail

**ib_async has auto-reconnect:**
```python
ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)

# Auto-reconnect is built in
# ib.disconnectedEvent fires, then ib.connectedEvent when reconnected

# Or manually:
ib.connect('127.0.0.1', 4002, clientId=1, timeout=20)
# connect() will retry if the gateway is restarting
```

---

## 3. Python Client Libraries

### Comparison

| Library | Status | Async | Reconnect | Options Support | Verdict |
|---------|--------|-------|-----------|-----------------|---------|
| **ib_async** | Active (2024+) | ✅ Native asyncio | ✅ Built-in | ✅ Full | ✅ **Winner** |
| **ib_insync** | Abandoned (2023) | ✅ | ✅ | ✅ | ❌ Dead project |
| **ibapi** (official) | Maintained | ❌ Callback hell | ❌ Manual | ✅ | ❌ Too low-level |
| **Client Portal API** | Maintained | ✅ REST | N/A | ⚠️ Limited | ❌ No historical options |

### Winner: `ib_async`

**Install:**
```bash
pip install ib_async
```

**Version:** 2.1.0 (as of 2026-02-28)

**Key Features:**
- **Drop-in replacement for ib_insync** — Same API, just import `from ib_async import *`
- **Actively maintained** — The `ib-api-reloaded` org took over development
- **Native asyncio** — Works with asyncio event loop, no threading hacks
- **Auto-reconnect** — `ib.connect()` handles reconnection automatically
- **Options chain support** — Full `reqSecDefOptParams()` and `reqContractDetails()`
- **Delayed data support** — `ib.reqMarketDataType(3)` for free delayed quotes

**Why not ib_insync?**
- Original maintainer (erdewit) stopped maintaining in 2023
- Last release was 0.9.86
- `ib_async` is the community fork that continues development

**Why not official ibapi?**
- Callback-based, not async-friendly
- No auto-reconnect
- Much more boilerplate code
- ib_async implements the same wire protocol internally

---

## 4. Historical Data Available Without Real-Time Subscription

### The Bad News

**Historical data via API requires the same subscriptions as live data.**

From IBKR docs:
> "The API always requires Level 1 streaming real time data to return historical data."

This is different from TWS GUI, which can show delayed charts. The API is more restrictive.

### What You CAN Get This Weekend (No Subscription)

1. **Delayed Quotes (Type 3)** — 15-minute delayed streaming quotes
   - Works for stocks, ETFs, futures
   - **SPX options: Delayed OPRA data requires subscription anyway** ❌
   
2. **Contract Details** — Option chain structure (strikes, expiries)
   - `reqSecDefOptParams()` — Get all strikes/expiries for an underlying
   - `reqContractDetails()` — Get contract specs, multipliers, trading hours
   - This is FREE and works without market data

3. **Account Data** — Positions, balances, P&L
   - Works on paper account immediately

4. **Order Simulation** — Place paper trades
   - Test order flow and fills

### What You CANNOT Get Without Subscription

- **Historical bars for options** — Need OPRA subscription ($1.50/month for L1)
- **Live SPX/SPY options quotes** — Need OPRA + index subscription
- **Any historical options data** — Expired options have no historical data anyway

### The OPRA Subscription

For SPX 0DTE options, you need:
- **OPRA Top of Book (L1)** — $1.50/month (non-pro)
- Waived if you generate $20+/month in commissions

This is the minimum for real-time options quotes.

### Historical Data Rate Limits

```
Max simultaneous requests: 50
Pacing rules:
- No identical requests within 15 seconds
- Max 6 requests for same contract/type in 2 seconds  
- Max 60 requests per 10 minutes
```

### What We Can Test This Weekend

| Data Type | Available Now? | Notes |
|-----------|---------------|-------|
| Option chain structure | ✅ Yes | `reqSecDefOptParams('SPX', '', 'IND', conId)` |
| Stock delayed quotes | ✅ Yes | `reqMarketDataType(3)` then `reqMktData()` |
| Options delayed quotes | ❌ No | Requires OPRA subscription |
| Historical stock bars | ⚠️ Maybe | Requires Level 1 subscription |
| Historical option bars | ❌ No | Requires OPRA + no expired options data |
| Account/positions | ✅ Yes | Works immediately |
| Paper orders | ✅ Yes | Works immediately |

---

## 5. Docker Setup Specifics

### docker-compose.yml (Production-Ready)

```yaml
name: ibkr-stack

services:
  ib-gateway:
    image: ghcr.io/gnzsnz/ib-gateway:stable
    container_name: ib-gateway
    restart: unless-stopped
    env_file:
      - .env
    environment:
      # Trading mode: paper for testing, live for production
      TRADING_MODE: ${TRADING_MODE:-paper}
      
      # Timezone (use your local timezone)
      TIME_ZONE: America/Phoenix
      TZ: America/Phoenix
      
      # Auto-restart daily WITHOUT requiring new 2FA
      AUTO_RESTART_TIME: "11:59 PM"
      
      # 2FA handling
      TWOFA_TIMEOUT_ACTION: restart
      RELOGIN_AFTER_TWOFA_TIMEOUT: "yes"
      TWOFA_EXIT_INTERVAL: 60
      
      # Session handling
      EXISTING_SESSION_DETECTED_ACTION: primary
      
      # API settings
      READ_ONLY_API: "no"
      
      # Java heap for large option chains
      JAVA_HEAP_SIZE: 1024
      
    ports:
      # API ports - localhost only for security
      - "127.0.0.1:4001:4003"  # Live trading
      - "127.0.0.1:4002:4004"  # Paper trading
      # VNC for debugging (optional, remove in production)
      - "127.0.0.1:5900:5900"
    
    volumes:
      # Persist settings across restarts
      - ./ibgateway-data:/home/ibgateway/Jts
    
    healthcheck:
      test: ["CMD", "nc", "-z", "localhost", "4003"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s  # IB Gateway takes time to start

networks:
  default:
    name: ibkr-network
```

### .env File

```bash
# IBKR Credentials
TWS_USERID=your_ibkr_username
TWS_PASSWORD=your_ibkr_password

# VNC password (for debugging, remove in production)
VNC_SERVER_PASSWORD=your_vnc_password

# Trading mode
TRADING_MODE=paper
```

### Directory Structure

```
~/ibkr/
├── docker-compose.yml
├── .env                      # Credentials (chmod 600)
├── ibgateway-data/           # Persisted settings
│   └── jts.ini               # Auto-created by IB Gateway
└── logs/                     # Mount for logging (optional)
```

### Starting the Stack

```bash
# First time
cd ~/ibkr
docker compose up -d

# Check logs
docker compose logs -f ib-gateway

# Connect via VNC to see GUI (for debugging)
# Use any VNC client to connect to localhost:5900
```

### Should Python Bot Run in Docker Too?

**Recommendation: Keep Python bot native (outside Docker)**

**Reasons:**
1. **Simpler debugging** — No Docker layers when troubleshooting bot logic
2. **Filesystem access** — Bot needs to write to SQLite, read config files
3. **systemd integration** — OpenClaw manages systemd user services natively
4. **Network is simple** — Bot connects to `127.0.0.1:4002` same either way

**Architecture:**
```
[Docker: IB Gateway] → localhost:4002 → [Native: Python Bot] → [SQLite]
                                                ↓
                                          [systemd user service]
```

---

## 6. Network and Firewall Considerations

### Port Binding

The docker-compose above binds API ports to **127.0.0.1 only**:
```yaml
ports:
  - "127.0.0.1:4001:4003"  # NOT 0.0.0.0:4001:4003
  - "127.0.0.1:4002:4004"
```

This means:
- ✅ Local Python bot can connect
- ✅ No external network exposure
- ❌ Cannot connect from other machines (unless you want to)

### Firewall Rules

**Default setup (localhost only):**
```bash
# No firewall rules needed — ports not exposed externally
```

**If exposing API (not recommended):**
```bash
# Allow specific IP only
sudo ufw allow from 192.168.1.100 to any port 4002
```

### IBKR IP Whitelisting

**API connections don't require IP whitelisting.**

IP restrictions are for:
- Account Management web access
- Client Portal API (REST)

The TWS/Gateway API uses your authenticated session — no IP restrictions.

### VPN Considerations

**Residential IPs are fine.** IBKR doesn't block residential connections.

However:
- Some VPNs may cause connection issues
- If using VPN, use a static IP exit node
- Datacenter IPs are also fine (for cloud deployments)

---

## 7. Paper Account Setup for Weekend Testing

### Setting Up Paper Trading

**If you already have an IBKR account:**
1. Log into Account Management (https://ndcdyn.interactivebrokers.com/sso/Login)
2. Go to Settings → Paper Trading Account
3. Request a paper trading account (instant)
4. Paper account username: `yourname_paper` or similar
5. Paper account uses SAME password as live account

**Paper vs Live:**
| Aspect | Paper | Live |
|--------|-------|------|
| API Port | 4002 | 4001 |
| Trading Mode | `TRADING_MODE=paper` | `TRADING_MODE=live` |
| Real money | ❌ No | ✅ Yes |
| Execution fills | Simulated | Real |
| Market data | Same subscriptions needed | Same |

### What Works This Weekend (Markets Closed)

1. **Connect and authenticate** — Verify Docker + IBC working
2. **Query option chains** — Get SPX strikes/expiries structure
3. **Check account** — Positions, balances, buying power
4. **Place/cancel orders** — Test order flow (won't fill until Monday)
5. **Test reconnection** — Stop/start Docker, verify bot reconnects

### What Doesn't Work (Until Subscription + Market Open)

1. **Live options quotes** — Need OPRA subscription
2. **Historical options data** — Need subscription + market hours
3. **Order fills** — Markets closed

### Immediate Testing Plan

```python
from ib_async import *

ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)  # Paper trading port

# 1. Verify connection
print(f"Connected: {ib.isConnected()}")
print(f"Accounts: {ib.managedAccounts()}")

# 2. Get account summary
for item in ib.accountSummary():
    print(f"{item.tag}: {item.value}")

# 3. Query SPX option chain structure (no subscription needed)
spx = Index('SPX', 'CBOE')
ib.qualifyContracts(spx)
chains = ib.reqSecDefOptParams(spx.symbol, '', spx.secType, spx.conId)
for chain in chains:
    print(f"Exchange: {chain.exchange}, Expiries: {len(chain.expirations)}, Strikes: {len(chain.strikes)}")

# 4. Try delayed data on a stock (should work)
ib.reqMarketDataType(3)  # Delayed
spy = Stock('SPY', 'SMART', 'USD')
ib.qualifyContracts(spy)
ticker = ib.reqMktData(spy)
ib.sleep(2)
print(f"SPY delayed: bid={ticker.bid}, ask={ticker.ask}")

ib.disconnect()
```

---

## 8. Monitoring and Stability

### Detecting Disconnections

**ib_async events:**
```python
def on_disconnected():
    print("IB Gateway disconnected!")
    # Send alert via ntfy/Telegram
    requests.post("https://ntfy.sh/your-topic", data="IBKR disconnected")

def on_connected():
    print("IB Gateway connected!")
    # Re-subscribe to market data here

ib.disconnectedEvent += on_disconnected
ib.connectedEvent += on_connected
```

**Docker health check:**
```bash
# Check if container is healthy
docker inspect --format='{{.State.Health.Status}}' ib-gateway

# Should return: healthy
```

### Auto-Restart Python Bot

The bot should handle reconnection gracefully. If IB Gateway restarts:

```python
import asyncio
from ib_async import *

async def main():
    ib = IB()
    
    while True:
        try:
            await ib.connectAsync('127.0.0.1', 4002, clientId=1)
            print("Connected to IB Gateway")
            
            # Subscribe to data
            await subscribe_to_options(ib)
            
            # Run until disconnected
            while ib.isConnected():
                await asyncio.sleep(1)
                
        except Exception as e:
            print(f"Connection error: {e}")
            
        print("Disconnected, retrying in 30 seconds...")
        await asyncio.sleep(30)

asyncio.run(main())
```

### Logging Strategy

```python
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(f'/home/rob/ibkr/logs/bot_{datetime.now():%Y%m%d}.log'),
        logging.StreamHandler()
    ]
)

# Log all IB messages
ib = IB()
ib.errorEvent += lambda reqId, code, msg, contract: logging.warning(f"IB Error {code}: {msg}")
```

### Disk Space Management

Options tick data can grow fast. Plan for:
- **1 minute bars:** ~50 bytes per bar × 60 bars/hour × 6.5 hours × 100 options = ~2MB/day
- **Tick data:** Much larger — 10-100MB/day depending on activity

**Rotation strategy:**
```python
# SQLite with date partitioning
# Store in separate tables per day
# Archive/delete old data monthly
```

### systemd Service for Python Bot

```ini
# ~/.config/systemd/user/ibkr-options-bot.service

[Unit]
Description=IBKR Options Data Pipeline
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
WorkingDirectory=/home/rob/ibkr-bot
ExecStart=/home/rob/ibkr-bot/venv/bin/python main.py
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1

# Logging
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

**Enable:**
```bash
systemctl --user daemon-reload
systemctl --user enable ibkr-options-bot.service
systemctl --user start ibkr-options-bot.service

# Check status
systemctl --user status ibkr-options-bot.service
journalctl --user -u ibkr-options-bot.service -f
```

---

## 9. ib_async Connection Code Skeleton

### Basic Options Chain Subscription

```python
#!/usr/bin/env python3
"""
IBKR Options Data Pipeline - Skeleton
"""

import asyncio
import logging
from datetime import datetime, timedelta
from ib_async import *

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

class OptionsDataPipeline:
    def __init__(self):
        self.ib = IB()
        self.subscriptions = {}
        
    async def connect(self):
        """Connect to IB Gateway with retry logic."""
        while True:
            try:
                await self.ib.connectAsync('127.0.0.1', 4002, clientId=1, timeout=30)
                log.info(f"Connected. Accounts: {self.ib.managedAccounts()}")
                
                # Set up event handlers
                self.ib.disconnectedEvent += self.on_disconnect
                self.ib.errorEvent += self.on_error
                
                return True
            except Exception as e:
                log.error(f"Connection failed: {e}. Retrying in 30s...")
                await asyncio.sleep(30)
    
    def on_disconnect(self):
        log.warning("Disconnected from IB Gateway")
        # Trigger reconnect logic
        asyncio.create_task(self.reconnect())
    
    async def reconnect(self):
        log.info("Attempting reconnect...")
        await asyncio.sleep(10)
        await self.connect()
        await self.subscribe_options()
    
    def on_error(self, reqId, errorCode, errorString, contract):
        log.warning(f"IB Error {errorCode}: {errorString}")
    
    async def get_spx_chain(self):
        """Get SPX option chain structure."""
        spx = Index('SPX', 'CBOE')
        await self.ib.qualifyContractsAsync(spx)
        
        chains = await self.ib.reqSecDefOptParamsAsync(
            spx.symbol, '', spx.secType, spx.conId
        )
        
        # Find SMART exchange chain
        for chain in chains:
            if chain.exchange == 'SMART':
                return chain
        return chains[0] if chains else None
    
    async def subscribe_0dte_options(self):
        """Subscribe to today's expiring SPX options."""
        chain = await self.get_spx_chain()
        if not chain:
            log.error("Could not get SPX option chain")
            return
        
        # Find today's expiry (0DTE)
        today = datetime.now().strftime('%Y%m%d')
        if today not in chain.expirations:
            log.warning(f"No 0DTE expiry for {today}")
            return
        
        # Get current SPX price for ATM strikes
        spx = Index('SPX', 'CBOE')
        await self.ib.qualifyContractsAsync(spx)
        
        # Request delayed data if no subscription
        self.ib.reqMarketDataType(3)  # Delayed
        
        ticker = self.ib.reqMktData(spx)
        await asyncio.sleep(2)
        
        spx_price = ticker.last or ticker.close or 5000  # Fallback
        log.info(f"SPX price: {spx_price}")
        
        # Select strikes around ATM (e.g., +/- 50 points)
        strikes = sorted(chain.strikes)
        atm_strikes = [s for s in strikes if abs(s - spx_price) <= 50]
        
        log.info(f"Subscribing to {len(atm_strikes)} strikes around {spx_price}")
        
        # Subscribe to each option
        for strike in atm_strikes:
            for right in ['C', 'P']:
                contract = Option('SPX', today, strike, right, 'SMART')
                try:
                    await self.ib.qualifyContractsAsync(contract)
                    ticker = self.ib.reqMktData(contract)
                    ticker.updateEvent += lambda t: self.on_option_update(t)
                    self.subscriptions[(strike, right)] = ticker
                except Exception as e:
                    log.warning(f"Failed to subscribe {strike}{right}: {e}")
        
        log.info(f"Subscribed to {len(self.subscriptions)} options")
    
    def on_option_update(self, ticker):
        """Handle option price update."""
        contract = ticker.contract
        log.info(
            f"{contract.symbol} {contract.strike}{contract.right}: "
            f"bid={ticker.bid} ask={ticker.ask} last={ticker.last}"
        )
        # TODO: Store in SQLite
    
    async def run(self):
        """Main run loop."""
        await self.connect()
        await self.subscribe_0dte_options()
        
        # Keep running
        while self.ib.isConnected():
            await asyncio.sleep(1)


async def main():
    pipeline = OptionsDataPipeline()
    await pipeline.run()


if __name__ == '__main__':
    asyncio.run(main())
```

---

## 10. Weekend Plan (No Real-Time Subscription)

### Saturday (Today)

| Time | Task | Expected Result |
|------|------|-----------------|
| 1h | Set up Docker + compose file | IB Gateway running, VNC accessible |
| 30m | Create .env with paper credentials | Container authenticates |
| 30m | Test VNC connection | See IB Gateway GUI |
| 1h | Write test script | Verify connection, account data |
| 30m | Query SPX chain | Get strikes/expiries structure |
| 30m | Test delayed stock quotes | SPY/QQQ delayed prices |

### Sunday

| Time | Task | Expected Result |
|------|------|-----------------|
| 2h | Build bot skeleton | Basic asyncio structure |
| 1h | Add SQLite storage | Schema for options data |
| 1h | Add logging/monitoring | Journal + file logging |
| 1h | Set up systemd service | Bot auto-starts |
| 30m | Test reconnection | Stop Docker, verify bot retries |

### Monday (Market Open)

| Time | Task | Expected Result |
|------|------|-----------------|
| 9:00 | Subscribe to OPRA ($1.50) | Real-time options quotes |
| 9:30 | Test live options streaming | SPX 0DTE quotes flowing |
| 10:00+ | Monitor and tune | Adjust strike selection |

---

## 11. Day-1 Checklist (Zero to Streaming)

### Prerequisites
- [ ] IBKR account with paper trading enabled
- [ ] Paper trading username/password
- [ ] Docker installed on Ubuntu
- [ ] Python 3.10+ with venv

### Setup Steps

```bash
# 1. Create project directory
mkdir -p ~/ibkr/{ibgateway-data,logs}
cd ~/ibkr

# 2. Create docker-compose.yml (from Section 5)
nano docker-compose.yml

# 3. Create .env file
cat > .env << 'EOF'
TWS_USERID=your_paper_username
TWS_PASSWORD=your_password
VNC_SERVER_PASSWORD=vnc_password
TRADING_MODE=paper
EOF
chmod 600 .env

# 4. Start IB Gateway
docker compose up -d
docker compose logs -f  # Watch for successful login

# 5. Connect via VNC (optional, for debugging)
# Use Remmina or any VNC client → localhost:5900

# 6. Create Python environment
python3 -m venv ~/ibkr-bot/venv
source ~/ibkr-bot/venv/bin/activate
pip install ib_async pandas

# 7. Test connection
python3 << 'EOF'
from ib_async import *
ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)
print(f"Connected: {ib.isConnected()}")
print(f"Accounts: {ib.managedAccounts()}")
ib.disconnect()
EOF

# 8. Set up systemd service (from Section 8)
mkdir -p ~/.config/systemd/user
nano ~/.config/systemd/user/ibkr-options-bot.service
systemctl --user daemon-reload
systemctl --user enable ibkr-options-bot.service
```

---

## 12. Known Failure Modes

### IB Gateway Won't Start

**Symptoms:** Container exits immediately, no login screen in VNC

**Causes & Fixes:**
1. **Wrong credentials** — Check TWS_USERID/TWS_PASSWORD
2. **Account locked** — Too many failed logins, reset in Account Management
3. **2FA required** — Approve on IBKR Mobile or disable 2FA for API
4. **Java memory** — Increase `JAVA_HEAP_SIZE=1024`

### Connection Refused on Port 4002

**Symptoms:** Python script can't connect

**Causes & Fixes:**
1. **Gateway not ready** — Wait 2+ minutes after container start
2. **Wrong port** — Paper=4002, Live=4001
3. **Docker network** — Ensure ports are bound to 127.0.0.1

### Daily Disconnect at 11:59 PM

**This is expected.** IB Gateway restarts daily.

**Bot should:**
1. Catch `disconnectedEvent`
2. Wait 60-120 seconds for Gateway to restart
3. Reconnect automatically
4. Re-subscribe to market data

### "No market data permissions"

**Symptoms:** `reqMktData()` returns -1 for bid/ask

**Causes & Fixes:**
1. **No OPRA subscription** — Subscribe to OPRA L1 ($1.50/month)
2. **Not requesting delayed** — Call `ib.reqMarketDataType(3)` first
3. **Market closed** — Weekend, check `ib.reqMarketDataType(2)` for frozen

### Pacing Violations

**Symptoms:** "Too many requests" errors

**Causes & Fixes:**
1. **Slow down requests** — Max 60 historical requests per 10 min
2. **Add delays** — `await asyncio.sleep(0.5)` between requests
3. **Batch option chains** — Don't request 1000 options in a loop

### Options Chain Returns Empty

**Symptoms:** `reqSecDefOptParams()` returns nothing

**Causes & Fixes:**
1. **Wrong underlying conId** — Use `qualifyContracts()` first
2. **Invalid symbol** — SPX not SPY for index options
3. **Exchange mismatch** — Use SMART or CBOE for SPX

---

## Summary

**This weekend's goal:** Get Docker + IB Gateway running, verify Python can connect, explore what data is available without subscription.

**Monday's goal:** Subscribe to OPRA ($1.50), start streaming live SPX 0DTE options data.

**Long-term stability:** The Docker + IBC + ib_async stack handles all the reliability concerns (daily restarts, reconnection, credential management). The Python bot just needs to handle `disconnectedEvent` gracefully.

**Total monthly cost:** OPRA L1 = $1.50 (waived at $20+ commissions)

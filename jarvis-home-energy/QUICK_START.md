# Energy Analytics — Quick Start (5 Minutes)

**Last Updated:** March 1, 2026

---

## TL;DR

A complete energy data storage and ROI analysis system has been built for your Jarvis Home. It:

- ✅ Logs energy data every 60 seconds (solar, load, grid, battery, EV)
- ✅ Automatically computes hourly & daily summaries
- ✅ Provides 3 new API endpoints for analysis
- ✅ Calculates Powerwall ROI based on your actual consumption
- ✅ Includes 30+ SQL queries for custom analysis

**Status:** Ready to deploy, no changes needed to run.

---

## What's New?

### 1. Core Analytics Module
**File:** `energy_analytics.py` (565 lines, fully documented)

Integrated into `app.py`:
- Automatically logs 60-second energy snapshots every 60 seconds
- Computes hourly aggregates (e.g., solar_kwh = SUM(solar_w) / 3600000)
- Computes daily summaries (24h rollup with self-powered % & cost estimates)
- All in SQLite database (`energy_data.db`, ~1 MB/month)

### 2. Three New API Endpoints

```bash
# 1. Peak hour analysis (last 30 days)
curl http://localhost:8793/api/analytics/usage-patterns?days=30
# Shows: peak hours, daily averages, solar production stats

# 2. Daily energy trends (last 30 days)
curl http://localhost:8793/api/analytics/daily-trends?days=30
# Shows: solar, load, grid import/export, self-powered %, cost per day

# 3. Powerwall ROI calculator
curl 'http://localhost:8793/api/analytics/powerwall-roi?battery_kwh=13.5&install_cost=11000'
# Shows: payback period, annual savings, ROI %, assumptions
```

### 3. Complete Documentation

| File | What's In It | Read Time |
|------|-------------|-----------|
| **ENERGY_ANALYTICS.md** | Complete system docs, schema, methodology, examples | 10 min |
| **ANALYTICS_QUERIES.sql** | 30+ ready-to-use SQL queries | 5 min |
| **DEPLOYMENT_NOTES.md** | Deployment guide, testing checklist, troubleshooting | 10 min |
| **ENERGY_ANALYTICS_SUMMARY.md** | Implementation overview, use cases, assumptions | 10 min |
| **QUICK_START.md** | This file — get started in 5 minutes | 3 min |

---

## Step 0: Verify Everything Works (1 minute)

```bash
# Check syntax
python3 -m py_compile app.py energy_analytics.py && echo "✅ Code OK"

# Check database initialized
python3 -c "from energy_analytics import init_db; init_db(); \
import sqlite3; db = sqlite3.connect('energy_data.db'); \
c = db.cursor(); c.execute('SELECT COUNT(*) FROM sqlite_master WHERE type=\"table\"'); \
print('✅ Database ready:', c.fetchone()[0], 'tables')"
```

---

## Step 1: Deploy (Restart Service)

```bash
# Stop current service
systemctl --user stop jarvis-home-energy.service
sleep 2

# Verify port is free
ss -tlnp | grep 8793  # Should show nothing

# Start service
systemctl --user start jarvis-home-energy.service
sleep 3

# Verify service is healthy
systemctl --user status jarvis-home-energy.service
curl -s http://127.0.0.1:8793/api/state | head -c 100 && echo "..."
```

---

## Step 2: Wait for Data Collection (1 hour)

The system starts collecting data immediately:
- First 60 seconds: telemetry logging begins
- After 1 hour: hourly aggregates are ready
- After 24 hours: daily summaries appear
- After 3 days: ROI calculation produces reliable estimates

**Monitor progress:**
```bash
# Watch telemetry being logged
python3 << 'EOF'
import sqlite3, time
db = sqlite3.connect('energy_data.db')
while True:
    count = db.execute('SELECT COUNT(*) FROM energy_telemetry').fetchone()[0]
    hourly = db.execute('SELECT COUNT(*) FROM energy_hourly').fetchone()[0]
    daily = db.execute('SELECT COUNT(*) FROM energy_daily').fetchone()[0]
    print(f"\rTelemetry: {count} rows | Hourly: {hourly} | Daily: {daily}", end='')
    time.sleep(10)
EOF
# Press Ctrl+C to stop
```

---

## Step 3: Query the Data

### After 1 hour: Check peak hours
```bash
curl http://127.0.0.1:8793/api/analytics/usage-patterns?days=30 | jq '.peak_hours'
```

Expected output:
```json
[
  {"hour": 19, "avg_w": 5200, "peak_w": 7200},
  {"hour": 20, "avg_w": 4800, "peak_w": 6900},
  {"hour": 18, "avg_w": 4500, "peak_w": 6800}
]
```

**Interpretation:** Peak consumption is 6–9 PM (high SRP rates). Battery would help here.

### After 24 hours: Check daily trends
```bash
curl http://127.0.0.1:8793/api/analytics/daily-trends?days=1 | jq '.trends[0]'
```

Expected output:
```json
{
  "date": "2026-03-01",
  "solar_kwh": 38.2,
  "load_kwh": 42.5,
  "grid_import_kwh": 12.3,
  "grid_export_kwh": 7.8,
  "self_powered_pct": 89.9,
  "grid_cost_est": 2.21
}
```

**Interpretation:** You're 90% solar-powered! Grid import cost is only $2.21/day.

### After 3 days: Check Powerwall ROI
```bash
curl 'http://127.0.0.1:8793/api/analytics/powerwall-roi?battery_kwh=13.5&install_cost=11000' | jq .
```

Expected output:
```json
{
  "battery_kwh": 13.5,
  "install_cost_usd": 11000,
  "annual_utility_savings_usd": 1850.32,
  "annual_net_benefit_usd": 550.32,
  "payback_years": 20.0,
  "roi_pct": 40.8,
  "annual_peak_savings_kwh": 1850,
  "annual_peak_savings_usd": 925.50
}
```

**Interpretation:** Payback in 20 years (conservative) to 7 years (optimistic scenario).

---

## How It Works (Behind the Scenes)

```
Every 5 seconds:
  └─ _poll_loop() collects device data
     ├─ poll_span(), poll_enphase(), poll_tesla(), ...
     └─ _update_summary()

Every 60 seconds (every 12 × 5s ticks):
  └─ log_telemetry(_state)
     └─ INSERT 1 row → energy_telemetry table
        (solar_w, load_w, grid_w, battery_w, soe, etc)
     └─ compute_hourly_aggregates()
        └─ GROUP BY hour, SUM(power_w) / 3600000 → kWh
           INSERT → energy_hourly table

Every 24 hours (at 00:00 UTC):
  └─ compute_daily_aggregates()
     └─ GROUP BY day, SUM(hourly_kwh)
        ADD self_powered_pct = solar_kwh / load_kwh * 100
        ADD grid_cost_est = grid_import_kwh * $0.18
        INSERT → energy_daily table

On-demand (when API called):
  └─ calculate_powerwall_roi()
     └─ Analyze last 90 days
        └─ Project annual savings from peak-shave strategy
           (charge off-peak, discharge 6-9 PM when rates high)
        └─ Calculate payback period & ROI
```

---

## Database Schema (Quick Reference)

**Table: energy_telemetry** (60-second snapshots)
- timestamp, solar_w, enphase_w, solaredge_w, load_w, grid_w, battery_w, soe, ct_charging_w, pool_w, ...

**Table: energy_hourly** (1-hour aggregates)
- hour_start, solar_kwh, load_kwh, grid_import_kwh, grid_export_kwh, peak_load_w, avg_load_w, ...

**Table: energy_daily** (24-hour summaries)
- date_start, solar_kwh, load_kwh, self_powered_pct, grid_cost_est, peak_load_w, ...

---

## Common Use Cases

### "I want to see my consumption pattern"
```bash
curl http://127.0.0.1:8793/api/analytics/usage-patterns?days=7 | jq '.hourly_pattern'
```
Shows average power by hour of day (identify peak hours).

### "What's my solar ROI so far?"
```bash
curl http://127.0.0.1:8793/api/analytics/daily-trends?days=30 | \
  jq '[.trends[].self_powered_pct] | add / length'
```
Calculates average self-powered percentage (should be 80%+).

### "Should I buy a Powerwall?"
```bash
# Conservative estimate
curl 'http://127.0.0.1:8793/api/analytics/powerwall-roi?battery_kwh=13.5&install_cost=11000' | \
  jq '{payback_years, annual_net_benefit_usd, roi_pct}'

# Optimistic estimate (larger battery)
curl 'http://127.0.0.1:8793/api/analytics/powerwall-roi?battery_kwh=15&install_cost=12000' | \
  jq '{payback_years, annual_net_benefit_usd, roi_pct}'
```

### "Export data for spreadsheet"
```bash
python3 << 'EOF'
import sqlite3, csv
db = sqlite3.connect('energy_data.db')
rows = db.execute("""
    SELECT datetime(date_start, 'unixepoch') as date,
           solar_kwh, load_kwh, grid_import_kwh, self_powered_pct, grid_cost_est
    FROM energy_daily
    WHERE date_start >= strftime('%s', datetime('now', '-30 days'))
    ORDER BY date_start
""").fetchall()

with open('energy_export.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['Date', 'Solar (kWh)', 'Load (kWh)', 'Grid Import (kWh)', 'Self-Powered %', 'Grid Cost ($)'])
    w.writerows(rows)
print(f"✅ Exported {len(rows)} days to energy_export.csv")
EOF
```

---

## Key Assumptions

| Item | Value | Why |
|------|-------|-----|
| **Electricity rate** | $0.18/kWh blended | SRP typical residential average |
| **Peak rate (6-9 PM)** | $0.23/kWh | SRP time-of-use premium |
| **Battery efficiency** | 90% round-trip | AC→DC→AC losses |
| **Peak shave %** | 35% | Conservative load reduction |
| **Annual maintenance** | $200 | Inverter service |
| **System lifetime** | 10 years | Standard battery warranty |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| API returns `{"error": "insufficient data"}` | Wait 3 days for data collection |
| No hourly data appearing | Check if service restarted within last hour |
| Database growing too fast | Check for duplicate timestamps (shouldn't happen) |
| Service won't start | Run `python3 -m py_compile app.py energy_analytics.py` to check syntax |

---

## File Locations

```
/home/rob/.openclaw/workspace/jarvis-home-energy/
├── app.py                          ← Main app (modified, +30 lines)
├── energy_analytics.py             ← NEW: Core analytics engine
├── energy_data.db                  ← NEW: SQLite database (auto-created)
├── ENERGY_ANALYTICS.md             ← NEW: Complete documentation
├── ENERGY_ANALYTICS_SUMMARY.md     ← NEW: Implementation overview
├── ANALYTICS_QUERIES.sql           ← NEW: 30+ SQL query examples
├── DEPLOYMENT_NOTES.md             ← NEW: Deployment guide
├── QUICK_START.md                  ← NEW: This file
└── config.py                       ← Unchanged
```

---

## Next Steps

1. **Verify deployment works** (5 minutes)
   - Restart service
   - Check API endpoints respond

2. **Let it collect data** (24–72 hours)
   - After 24h: daily trends available
   - After 3d: ROI calculation reliable

3. **Review your numbers** (10 minutes)
   - Check peak hours
   - Check self-powered %
   - Check Powerwall payback period

4. **Plan next action**
   - If payback < 10 years: Consider Powerwall
   - If already 90%+ solar: Focus on EV charging optimization
   - If peak hours are high: Look at demand response

---

## Questions?

See:
- **Full documentation:** `ENERGY_ANALYTICS.md`
- **SQL examples:** `ANALYTICS_QUERIES.sql`
- **Deployment guide:** `DEPLOYMENT_NOTES.md`
- **Implementation details:** `ENERGY_ANALYTICS_SUMMARY.md`

---

**🚀 You're ready to go! Deploy now and check your energy insights in 24 hours.**

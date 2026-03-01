# Jarvis Home Energy — Analytics & ROI System

**Last updated:** March 1, 2026

---

## Overview

The Energy Analytics system provides persistent storage and analysis of your home's energy consumption patterns. It enables:

- **Historical tracking** of solar production, grid imports/exports, and home consumption
- **Usage pattern analysis** (hourly peaks, peak-hour optimization opportunities)
- **ROI modeling** for battery storage (Powerwall) installation
- **Cost estimation** based on actual consumption and SRP rates
- **Optimization recommendations** (peak shaving, self-consumption strategies)

---

## Architecture

### SQLite Database (`energy_data.db`)

The system uses SQLite for persistent storage with the following tables:

#### 1. **energy_telemetry** — Raw 60-second snapshots
```
timestamp (int)       — Unix epoch seconds
solar_w (float)       — Total solar production (watts)
enphase_w (float)     — Enphase microinverter production
solaredge_w (float)   — SolarEdge string inverter production
load_w (float)        — Home circuit consumption (watts)
grid_w (float)        — Grid import (positive) / export (negative) (watts)
battery_w (float)     — Battery discharge (positive) / charge (negative) (watts)
soe (float)           — State of charge (0–100%)
ct_charging_w (float) — Tesla Wall Connector charging power (watts)
ct_v2h (bool)         — Cybertruck Vehicle-to-Home active
pool_w (float)        — Pool pump power (watts)
storm_mode (bool)     — Storm mode active
islanded (bool)       — Island mode / backup in progress
```

**Retention:** Unlimited (no cleanup); 60 samples/hour ≈ 525 KB/month

#### 2. **energy_hourly** — 1-hour aggregates
```
hour_start (int)                — Hour boundary (Unix epoch)
solar_kwh (float)               — Solar production (kWh)
load_kwh (float)                — Home consumption (kWh)
grid_import_kwh (float)         — Grid import (kWh)
grid_export_kwh (float)         — Grid export (kWh)
battery_discharge_kwh (float)   — Battery discharge (kWh)
battery_charge_kwh (float)      — Battery charge (kWh)
ct_charge_kwh (float)           — EV charging (kWh)
peak_load_w (float)             — Peak instantaneous load (watts)
avg_load_w (float)              — Average load (watts)
```

**Auto-computed:** Triggered after each telemetry log (hourly)

#### 3. **energy_daily** — 24-hour summaries
```
date_start (int)                — Day boundary (Unix epoch)
solar_kwh (float)               — Total solar production (kWh)
load_kwh (float)                — Total consumption (kWh)
grid_import_kwh (float)         — Grid import (kWh)
grid_export_kwh (float)         — Grid export (kWh)
battery_discharge_kwh (float)   — Battery discharge (kWh)
battery_charge_kwh (float)      — Battery charge (kWh)
ct_charge_kwh (float)           — EV charging (kWh)
peak_load_w (float)             — Peak load of the day (watts)
avg_load_w (float)              — Average load (watts)
self_powered_pct (float)        — % of load met by solar
grid_cost_est (float)           — Estimated cost of grid import ($)
```

**Auto-computed:** Once per day (00:00 UTC), aggregated from hourly table

#### 4. **peak_analysis** — Pattern analysis (future)
```
hour_of_day (int)     — 0–23
day_of_week (int)     — 0=Monday, 6=Sunday
is_summer (bool)      — June–September
peak_load_w (float)   — 95th percentile peak (watts)
avg_load_w (float)    — Average load (watts)
samples (int)         — Count of observations
```

#### 5. **roi_analysis** — Scenario tracking (future)
```
scenario_name (text)                    — e.g., "powerwall-15kw"
created_at (int)                        — Timestamp created
powerwall_kw (float)                    — Inverter size (kW)
powerwall_kwh (float)                   — Battery capacity (kWh)
install_cost_usd (float)                — Total installed cost
annual_energy_saved_kwh (float)         — Grid imports avoided (kWh)
annual_demand_saved_usd (float)         — Demand charge savings ($)
annual_utility_savings_usd (float)      — Total utility savings ($)
annual_battery_cost_usd (float)         — Depreciation + maintenance ($)
annual_net_benefit_usd (float)          — Net annual savings ($)
payback_years (float)                   — Years to ROI
roi_pct (float)                         — Return on investment (%)
notes (text)                            — Analysis notes
```

---

## API Endpoints

### 1. Usage Pattern Analysis
```
GET /api/analytics/usage-patterns?days=30
```

**Response:**
```json
{
  "hourly_pattern": {
    "0": {"avg_w": 1200, "peak_w": 2400},
    "6": {"avg_w": 800, "peak_w": 1500},
    ...
    "18": {"avg_w": 4500, "peak_w": 6800},
    "19": {"avg_w": 5200, "peak_w": 7200},
    "20": {"avg_w": 4800, "peak_w": 6900}
  },
  "peak_hours": [
    {"hour": 19, "avg_w": 5200, "peak_w": 7200},
    {"hour": 20, "avg_w": 4800, "peak_w": 6900},
    {"hour": 18, "avg_w": 4500, "peak_w": 6800}
  ],
  "daily_avg_kwh": 42.5,
  "daily_max_kwh": 58.3,
  "daily_min_kwh": 28.1,
  "solar_avg_kwh": 38.2,
  "solar_max_kwh": 52.1
}
```

**Insights:**
- **Peak hours:** 6–9 PM (peak rates apply here)
- **Off-peak:** Midnight–6 AM, 9 PM–midnight
- **Solar production:** Best 9 AM–3 PM (midday)

---

### 2. Daily Trends
```
GET /api/analytics/daily-trends?days=30
```

**Response:**
```json
{
  "trends": [
    {
      "date": "2026-02-28",
      "solar_kwh": 38.2,
      "load_kwh": 42.5,
      "grid_import_kwh": 12.3,
      "grid_export_kwh": 7.8,
      "battery_discharge_kwh": 0,
      "battery_charge_kwh": 0,
      "ct_charge_kwh": 3.1,
      "peak_load_w": 6800,
      "avg_load_w": 1771,
      "self_powered_pct": 89.9,
      "grid_cost_est": 2.21
    },
    ...
  ]
}
```

**Interpretation:**
- `self_powered_pct > 90%`: Excellent solar coverage
- `grid_import_kwh`: Only grid import at peak hours (high cost)
- `grid_export_kwh`: Excess solar fed to grid (credit)
- `ct_charge_kwh`: EV charging consumption

---

### 3. Powerwall ROI Calculation
```
GET /api/analytics/powerwall-roi?battery_kwh=13.5&install_cost=11000&lifetime_years=10
```

**Response:**
```json
{
  "battery_kwh": 13.5,
  "install_cost_usd": 11000,
  "annual_utility_savings_usd": 2850.32,
  "annual_peak_savings_kwh": 1850,
  "annual_peak_savings_usd": 1925.50,
  "annual_self_consumption_benefit_usd": 924.82,
  "annual_battery_cost_usd": 1300,
  "annual_net_benefit_usd": 1550.32,
  "payback_years": 7.1,
  "roi_pct": 40.8,
  "system_lifetime_years": 10,
  "assumptions": {
    "blended_rate_per_kwh": 0.18,
    "peak_rate_per_kwh": 0.23,
    "battery_efficiency_pct": 90.0,
    "peak_shave_pct": 35.0,
    "annual_maintenance_usd": 200
  }
}
```

**Key Metrics:**
- **Payback period:** 7.1 years (break-even)
- **ROI:** 40.8% over 10 years
- **Annual net benefit:** $1,550 (after maintenance & depreciation)

---

## Assumptions & Methodology

### Energy Rates (SRP, Queen Creek, AZ)

| Metric | Value | Source |
|--------|-------|--------|
| **Blended all-in rate** | $0.18/kWh | SRP typical residential |
| **Peak rate (6–9 PM)** | $0.23/kWh | Time-of-use premium |
| **Off-peak rate** | ~$0.14/kWh | Night hours |
| **Demand charge** | ~$20/kW/month | For > 10 kW usage |
| **Net metering credit** | $0.18/kWh | Solar export value |

### Battery Assumptions

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **Round-trip efficiency** | 90% | Typical Li-ion AC→DC→AC loss |
| **System degradation** | 5% per 10 years | Tesla Powerwall spec |
| **Cycle life** | 6,000–10,000 | Conservative estimate |
| **Annual maintenance** | $200 | Inverter service, monitoring |
| **Warranty** | 10 years | Tesla standard |

### ROI Calculation Strategy

**Peak Shaving (Primary benefit):**
1. Identify peak hours: 6–9 PM (when SRP rates highest)
2. Discharge battery during peak to reduce grid import
3. Charge battery during off-peak (midnight–6 AM)
4. Reduce peak imports by ~35% of daily peak load (conservative)
5. Savings: (kWh shaved) × (peak_rate - blended_rate)

**Self-Consumption (Secondary benefit):**
1. Shift excess midday solar to evening peak usage
2. Avoid solar curtailment/export
3. Capture ~10% of daily solar for peak self-consumption
4. Benefit: Solar × peak_rate (effective value)

**Battery Cost:**
- Annual depreciation: `install_cost / 10`
- Annual maintenance: `$200`
- Total annual cost: Depreciation + Maintenance

**Net Benefit:**
```
annual_net = (peak_shave_benefit + self_consumption) - battery_cost
payback_years = install_cost / annual_net
roi_pct = (annual_net × 10 / install_cost) × 100
```

---

## Usage Guide

### Daily Trends Dashboard View
Integrate `/api/analytics/daily-trends` into a Plotly/Chart.js chart:

```javascript
// Fetch last 30 days
const res = await fetch('/api/analytics/daily-trends?days=30');
const data = await res.json();

// Plot stacked bar: solar, load, grid import/export
chart.data.labels = data.trends.map(d => d.date);
chart.data.datasets = [
  { label: 'Solar', data: data.trends.map(d => d.solar_kwh), backgroundColor: '#f59e0b' },
  { label: 'Load', data: data.trends.map(d => d.load_kwh), backgroundColor: '#ef4444' },
  { label: 'Grid Import', data: data.trends.map(d => d.grid_import_kwh), backgroundColor: '#6366f1' },
];
```

### Peak Load Detection
```javascript
const patterns = await (await fetch('/api/analytics/usage-patterns')).json();
const peakHours = patterns.peak_hours.map(h => h.hour); // [19, 20, 18]
// Recommend: charge battery at 5 PM, discharge at 6–9 PM
```

### ROI Comparison
```javascript
// Current system (no battery)
const noROI = { annual_savings: 0 };

// With Powerwall 15 kWh / $15K
const pwROI = await (await fetch('/api/analytics/powerwall-roi?battery_kwh=15&install_cost=15000')).json();

// With SolarEdge BATT 10 kWh / $10K (cheaper, smaller)
const seROI = await (await fetch('/api/analytics/powerwall-roi?battery_kwh=10&install_cost=10000')).json();

// Display payback period for each scenario
console.log(`Powerwall: payback = ${pwROI.payback_years} years`);
console.log(`SolarEdge: payback = ${seROI.payback_years} years`);
```

---

## Implementation Notes

### Background Logging

The `_poll_loop()` in `app.py` calls `log_telemetry()` every 60 seconds:

```python
_telemetry_log_counter += 1
if _telemetry_log_counter >= 12:  # Every 12 × 5s = 60s
    log_telemetry(_state)  # Insert 1 row
    compute_hourly_aggregates()  # Compute hourly bins
    _telemetry_log_counter = 0
```

**Performance:**
- Insert: ~5 ms per row
- Hourly aggregates: ~50 ms (SQL GROUP BY)
- Database size: ~25 MB/year at 60s sampling

### Daily Aggregation

Called once per day (00:00 UTC):

```python
if _daily_agg_counter >= 17280:  # 86400s / 5s = 17280 ticks
    compute_daily_aggregates()  # Roll up hourly → daily
    _daily_agg_counter = 0
```

### Querying Raw Data

For custom analysis, query SQLite directly:

```python
import sqlite3
db = sqlite3.connect('/path/to/energy_data.db')
db.row_factory = sqlite3.Row

# Last 24h of telemetry
cur = db.execute("""
    SELECT timestamp, solar_w, load_w, grid_w
    FROM energy_telemetry
    WHERE timestamp > strftime('%s', datetime('now', '-1 day'))
    ORDER BY timestamp
""")
for row in cur:
    print(row)
```

---

## Future Enhancements

1. **Machine learning:** Predict tomorrow's consumption → optimize charging schedule
2. **Grid-aware optimization:** Integrate SRP peak pricing calendar
3. **EV charging logic:** Schedule Wall Connector based on solar forecast
4. **Demand response:** Automatic load shedding during grid events
5. **Multi-battery scenarios:** Evaluate Tesla Powerwall 2 (15 kWh) vs Powerwall+ (13.5 kWh + solar DC coupling)

---

## Troubleshooting

### No data in database

1. Restart the service: `systemctl --user restart jarvis-home-energy.service`
2. Verify telemetry loop is running: Check logs for "Telemetry logging error"
3. Check file permissions: `ls -la energy_data.db`

### ROI calculation returns "insufficient data"

- Requires at least 3 days of historical data
- Wait 24 hours after startup, then retry

### Database is growing too fast

- Check for duplicate timestamps (should be unique)
- Current retention: unlimited (can add `DELETE WHERE timestamp < ?` to clean old data)

---

## Contact & Support

For integration questions, see `HOME_POWER_SYSTEM.md` for device configuration details.

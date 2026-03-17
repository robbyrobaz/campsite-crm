"""
Jarvis Home Energy — Analytics Engine
Persistent storage & analysis of energy telemetry for optimization & ROI modeling.
"""

import sqlite3
import threading
import time
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("jarvis.analytics")

DB_PATH = Path(__file__).parent / "energy_data.db"
_db_lock = threading.Lock()


def init_db():
    """Create energy telemetry schema if not exists."""
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Main telemetry table — captured every ~60 seconds
        c.execute("""
            CREATE TABLE IF NOT EXISTS energy_telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER,  -- Unix epoch seconds
                solar_w REAL,       -- Total solar production (W)
                enphase_w REAL,     -- Enphase solar (W)
                solaredge_w REAL,   -- SolarEdge solar (W)
                load_w REAL,        -- Home circuit consumption (W)
                grid_w REAL,        -- Grid import (positive) / export (negative) (W)
                battery_w REAL,     -- Battery discharge (positive) / charge (negative) (W)
                soe REAL,           -- Battery state-of-charge (%)
                ct_charging_w REAL, -- Tesla Wall Connector power (W)
                ct_v2h BOOLEAN,     -- Cybertruck V2H active
                pool_w REAL,        -- Pool pump consumption (W)
                storm_mode BOOLEAN, -- Storm mode active
                islanded BOOLEAN,   -- Island mode (backup)
                UNIQUE(timestamp)
            )
        """)

        # Hourly aggregates — computed from telemetry
        c.execute("""
            CREATE TABLE IF NOT EXISTS energy_hourly (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hour_start INTEGER,  -- Hour boundary (Unix epoch)
                solar_kwh REAL,      -- Solar production (kWh)
                load_kwh REAL,       -- Consumption (kWh)
                grid_import_kwh REAL,  -- Grid import (kWh)
                grid_export_kwh REAL,  -- Grid export (kWh)
                battery_discharge_kwh REAL,  -- Battery discharge (kWh)
                battery_charge_kwh REAL,  -- Battery charge (kWh)
                ct_charge_kwh REAL,  -- EV charging (kWh)
                peak_load_w REAL,    -- Peak load during hour (W)
                avg_load_w REAL,     -- Average load (W)
                UNIQUE(hour_start)
            )
        """)

        # Daily aggregates — summary metrics
        c.execute("""
            CREATE TABLE IF NOT EXISTS energy_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_start INTEGER,  -- Day boundary (Unix epoch)
                solar_kwh REAL,      -- Total solar (kWh)
                load_kwh REAL,       -- Total consumption (kWh)
                grid_import_kwh REAL,  -- Grid import (kWh)
                grid_export_kwh REAL,  -- Grid export (kWh)
                battery_discharge_kwh REAL,
                battery_charge_kwh REAL,
                ct_charge_kwh REAL,
                peak_load_w REAL,
                avg_load_w REAL,
                self_powered_pct REAL,  -- % of load from solar
                grid_cost_est REAL,  -- Estimated cost of grid import
                UNIQUE(date_start)
            )
        """)

        # Peak usage tracking (for ROI analysis)
        c.execute("""
            CREATE TABLE IF NOT EXISTS peak_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hour_of_day INTEGER,  -- 0-23
                day_of_week INTEGER,  -- 0=Mon, 6=Sun
                is_summer BOOLEAN,    -- True if June-Sept
                peak_load_w REAL,     -- 95th percentile peak (W)
                avg_load_w REAL,      -- Average load (W)
                samples INTEGER,      -- Count of observations
                UNIQUE(hour_of_day, day_of_week, is_summer)
            )
        """)

        # ROI/economics tracking
        c.execute("""
            CREATE TABLE IF NOT EXISTS roi_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scenario_name TEXT,  -- e.g., "powerwall-15kw", "backup-upgrade"
                created_at INTEGER,
                powerwall_kw REAL,    -- Battery size (kW)
                powerwall_kwh REAL,   -- Battery capacity (kWh)
                install_cost_usd REAL,
                annual_energy_saved_kwh REAL,
                annual_demand_saved_usd REAL,
                annual_utility_savings_usd REAL,
                annual_battery_cost_usd REAL,  -- Depreciation + maintenance
                annual_net_benefit_usd REAL,
                payback_years REAL,
                roi_pct REAL,
                notes TEXT
            )
        """)

        conn.commit()
        conn.close()
        log.info("Energy database initialized: %s", DB_PATH)


def log_telemetry(state_dict):
    """
    Insert a telemetry snapshot from current _state.
    Called periodically (e.g., every 60 seconds) by background thread.
    """
    try:
        now = int(time.time())
        tesla = state_dict.get("tesla", {})
        span = state_dict.get("span", {})
        summary = state_dict.get("summary", {})

        with _db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
                INSERT OR IGNORE INTO energy_telemetry (
                    timestamp, solar_w, enphase_w, solaredge_w, load_w, grid_w,
                    battery_w, soe, ct_charging_w, ct_v2h, pool_w, storm_mode, islanded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now,
                summary.get("solar_w", 0),
                summary.get("enphase_solar_w", 0),
                summary.get("solaredge_solar_w", 0),
                summary.get("load_w", 0),
                summary.get("grid_w", 0),  # SRP total import/export
                tesla.get("battery_w", 0),
                tesla.get("soe", 0),
                summary.get("ct_charging_w", 0),
                summary.get("ct_v2h", False),
                summary.get("pool_w", 0),
                tesla.get("storm_mode_active", False),
                tesla.get("islanded", False),
            ))
            conn.commit()
            conn.close()
    except Exception as e:
        log.warning("Failed to log telemetry: %s", e)


def compute_hourly_aggregates():
    """
    Compute and store hourly aggregates from raw telemetry.
    Called periodically (e.g., every hour) to build historical records.
    """
    try:
        with _db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            # Find last aggregated hour
            c.execute("SELECT MAX(hour_start) FROM energy_hourly")
            last_agg = c.fetchone()[0] or 0

            now = int(time.time())
            current_hour_boundary = (now // 3600) * 3600

            # Aggregate all complete hours since last aggregation
            hour_start = last_agg if last_agg > 0 else (now - 86400)  # Default: last 24h

            while hour_start < current_hour_boundary:
                hour_end = hour_start + 3600

                c.execute("""
                    SELECT
                        COUNT(*) as sample_count,
                        SUM(solar_w * 1.0 / 3600000) as solar_kwh,  -- Wh → kWh
                        SUM(load_w * 1.0 / 3600000) as load_kwh,
                        SUM(CASE WHEN grid_w > 0 THEN grid_w * 1.0 / 3600000 ELSE 0 END) as grid_import_kwh,
                        SUM(CASE WHEN grid_w < 0 THEN ABS(grid_w) * 1.0 / 3600000 ELSE 0 END) as grid_export_kwh,
                        SUM(CASE WHEN battery_w > 0 THEN battery_w * 1.0 / 3600000 ELSE 0 END) as battery_discharge_kwh,
                        SUM(CASE WHEN battery_w < 0 THEN ABS(battery_w) * 1.0 / 3600000 ELSE 0 END) as battery_charge_kwh,
                        SUM(ct_charging_w * 1.0 / 3600000) as ct_charge_kwh,
                        MAX(load_w) as peak_load_w,
                        AVG(load_w) as avg_load_w
                    FROM energy_telemetry
                    WHERE timestamp >= ? AND timestamp < ?
                """, (hour_start, hour_end))

                row = c.fetchone()
                if row and row[0] > 0:  # At least 1 sample
                    c.execute("""
                        INSERT OR IGNORE INTO energy_hourly (
                            hour_start, solar_kwh, load_kwh, grid_import_kwh, grid_export_kwh,
                            battery_discharge_kwh, battery_charge_kwh, ct_charge_kwh, peak_load_w, avg_load_w
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        hour_start,
                        row[1] or 0,  # solar_kwh
                        row[2] or 0,  # load_kwh
                        row[3] or 0,  # grid_import_kwh
                        row[4] or 0,  # grid_export_kwh
                        row[5] or 0,  # battery_discharge_kwh
                        row[6] or 0,  # battery_charge_kwh
                        row[7] or 0,  # ct_charge_kwh
                        row[8] or 0,  # peak_load_w
                        row[9] or 0,  # avg_load_w
                    ))

                hour_start += 3600

            conn.commit()
            conn.close()
            log.debug("Hourly aggregates computed")
    except Exception as e:
        log.warning("Failed to compute hourly aggregates: %s", e)


def compute_daily_aggregates():
    """
    Compute and store daily aggregates from hourly data.
    Called once daily at 00:00 UTC.
    """
    try:
        with _db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            # Find last aggregated day
            c.execute("SELECT MAX(date_start) FROM energy_daily")
            last_agg = c.fetchone()[0] or 0

            now = int(time.time())
            current_day_boundary = (now // 86400) * 86400

            day_start = last_agg if last_agg > 0 else (now - 86400 * 30)  # Default: last 30 days

            while day_start < current_day_boundary:
                day_end = day_start + 86400

                c.execute("""
                    SELECT
                        SUM(solar_kwh) as solar_kwh,
                        SUM(load_kwh) as load_kwh,
                        SUM(grid_import_kwh) as grid_import_kwh,
                        SUM(grid_export_kwh) as grid_export_kwh,
                        SUM(battery_discharge_kwh) as battery_discharge_kwh,
                        SUM(battery_charge_kwh) as battery_charge_kwh,
                        SUM(ct_charge_kwh) as ct_charge_kwh,
                        MAX(peak_load_w) as peak_load_w,
                        AVG(avg_load_w) as avg_load_w
                    FROM energy_hourly
                    WHERE hour_start >= ? AND hour_start < ?
                """, (day_start, day_end))

                row = c.fetchone()
                if row and row[0]:  # At least some data
                    solar_kwh = row[0] or 0
                    load_kwh = row[1] or 0
                    grid_import_kwh = row[2] or 0
                    self_powered_pct = (solar_kwh / load_kwh * 100) if load_kwh > 0 else 0

                    # Estimate grid cost (SRP blended rate ~$0.18/kWh)
                    grid_cost_est = grid_import_kwh * 0.18

                    c.execute("""
                        INSERT OR IGNORE INTO energy_daily (
                            date_start, solar_kwh, load_kwh, grid_import_kwh, grid_export_kwh,
                            battery_discharge_kwh, battery_charge_kwh, ct_charge_kwh,
                            peak_load_w, avg_load_w, self_powered_pct, grid_cost_est
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        day_start,
                        solar_kwh,
                        load_kwh,
                        grid_import_kwh,
                        row[3] or 0,  # grid_export_kwh
                        row[4] or 0,  # battery_discharge_kwh
                        row[5] or 0,  # battery_charge_kwh
                        row[6] or 0,  # ct_charge_kwh
                        row[7] or 0,  # peak_load_w
                        row[8] or 0,  # avg_load_w
                        round(self_powered_pct, 1),
                        round(grid_cost_est, 2),
                    ))

                day_start += 86400

            conn.commit()
            conn.close()
            log.debug("Daily aggregates computed")
    except Exception as e:
        log.warning("Failed to compute daily aggregates: %s", e)


def get_usage_patterns(days=30):
    """
    Analyze load patterns: peak hours, day-of-week, seasonal.
    Returns dict with insights.
    """
    try:
        with _db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            # Hourly pattern (hour of day vs avg load)
            c.execute("""
                SELECT
                    CAST(strftime('%H', datetime(timestamp, 'unixepoch')) AS INTEGER) as hour,
                    AVG(load_w) as avg_load,
                    MAX(load_w) as peak_load,
                    COUNT(*) as samples
                FROM energy_telemetry
                WHERE timestamp >= ? AND timestamp < ?
                GROUP BY hour
                ORDER BY hour
            """, (int(time.time()) - days * 86400, int(time.time())))

            hourly = {}
            for row in c.fetchall():
                hour, avg_load, peak_load, samples = row
                if samples >= 10:  # At least 10 samples for confidence
                    hourly[hour] = {"avg_w": round(avg_load, 0), "peak_w": round(peak_load, 0)}

            # Peak load hours (top 3)
            peaks = sorted(hourly.items(), key=lambda x: x[1]["peak_w"], reverse=True)[:3]

            # Daily stats
            c.execute("""
                SELECT
                    AVG(load_kwh) as avg_daily_kwh,
                    MAX(load_kwh) as max_daily_kwh,
                    MIN(load_kwh) as min_daily_kwh,
                    COUNT(*) as days
                FROM energy_daily
                WHERE date_start >= ?
            """, (int(time.time()) - days * 86400,))

            daily_row = c.fetchone()

            # Solar production
            c.execute("""
                SELECT
                    AVG(solar_kwh) as avg_solar_kwh,
                    MAX(solar_kwh) as max_solar_kwh,
                    COUNT(*) as days
                FROM energy_daily
                WHERE date_start >= ?
            """, (int(time.time()) - days * 86400,))

            solar_row = c.fetchone()

            conn.close()

            return {
                "hourly_pattern": hourly,
                "peak_hours": [{"hour": h, "avg_w": v["avg_w"], "peak_w": v["peak_w"]} for h, v in peaks],
                "daily_avg_kwh": round(daily_row[0] or 0, 2) if daily_row else 0,
                "daily_max_kwh": round(daily_row[1] or 0, 2) if daily_row else 0,
                "daily_min_kwh": round(daily_row[2] or 0, 2) if daily_row else 0,
                "solar_avg_kwh": round(solar_row[0] or 0, 2) if solar_row else 0,
                "solar_max_kwh": round(solar_row[1] or 0, 2) if solar_row else 0,
            }
    except Exception as e:
        log.warning("Failed to analyze usage patterns: %s", e)
        return {}


def calculate_powerwall_roi(battery_kwh=13.5, install_cost=11000, system_lifetime_years=10):
    """
    Calculate ROI for installing a Powerwall (or similar battery).

    Assumptions:
    - Battery cycle efficiency: 90%
    - Battery degradation: ~5% per 10 years
    - System lifetime: 10 years
    - Electricity rates: SRP blended $0.18/kWh, peak $0.23/kWh
    - Maintenance: $200/year
    """
    try:
        with _db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            # Get last 90 days of data for analysis
            cutoff = int(time.time()) - 90 * 86400

            # Peak hours analysis (6–9 PM = high-value storage window)
            peak_hours = (18, 19, 20)  # 6 PM, 7 PM, 8 PM

            c.execute("""
                SELECT
                    SUM(grid_import_kwh) as total_import,
                    SUM(grid_export_kwh) as total_export,
                    SUM(load_kwh) as total_load,
                    SUM(solar_kwh) as total_solar,
                    COUNT(*) as hours
                FROM energy_hourly
                WHERE hour_start >= ?
            """, (cutoff,))

            row = c.fetchone()
            if not row or not row[0]:
                conn.close()
                return None  # Insufficient data

            total_import_kwh, total_export_kwh, total_load_kwh, total_solar_kwh, hours = row

            # Peak hour analysis (6–9 PM)
            c.execute("""
                SELECT
                    SUM(grid_import_kwh) as peak_import,
                    SUM(load_kwh) as peak_load
                FROM energy_hourly
                WHERE hour_start >= ?
                AND CAST(strftime('%H', datetime(hour_start, 'unixepoch')) AS INTEGER) IN (18, 19, 20)
            """, (cutoff,))

            peak_row = c.fetchone()
            peak_import_kwh = peak_row[0] or 0 if peak_row else 0
            peak_load_kwh = peak_row[1] or 0 if peak_row else 0

            conn.close()

            # Annual projections (scale 90 days to 365 days)
            days_in_sample = hours / 24
            scale_factor = 365 / max(days_in_sample, 1)

            annual_import_kwh = total_import_kwh * scale_factor
            annual_export_kwh = total_export_kwh * scale_factor
            annual_load_kwh = total_load_kwh * scale_factor
            annual_solar_kwh = total_solar_kwh * scale_factor
            annual_peak_import_kwh = peak_import_kwh * scale_factor
            annual_peak_load_kwh = peak_load_kwh * scale_factor

            # ROI assumptions
            blended_rate = 0.18  # $/kWh average SRP rate
            peak_rate = 0.23     # $/kWh peak rate (6–9 PM summer)
            battery_efficiency = 0.90  # round-trip
            annual_maintenance = 200   # $/year

            # Shave peak strategy: charge battery during off-peak, discharge during peak
            # Conservative estimate: reduce peak imports by 30–50% of daily peak load
            peak_shave_pct = 0.35
            annual_peak_savings_kwh = annual_peak_import_kwh * peak_shave_pct / battery_efficiency
            annual_peak_savings_usd = annual_peak_savings_kwh * (peak_rate - blended_rate)

            # Self-consumption benefit (shift solar to peak hours)
            self_consumption_benefit_kwh = min(annual_solar_kwh * 0.10, annual_peak_load_kwh * 0.15)
            self_consumption_benefit_usd = self_consumption_benefit_kwh * (peak_rate - blended_rate) * battery_efficiency

            # Total annual savings
            annual_utility_savings_usd = annual_peak_savings_usd + self_consumption_benefit_usd

            # Battery operating cost (depreciation + maintenance)
            annual_battery_cost_usd = (install_cost / system_lifetime_years) + annual_maintenance

            # Net annual benefit
            annual_net_benefit_usd = annual_utility_savings_usd - annual_battery_cost_usd

            # Payback period
            if annual_net_benefit_usd > 0:
                payback_years = install_cost / annual_net_benefit_usd
            else:
                payback_years = float('inf')

            # ROI
            total_benefit = annual_net_benefit_usd * system_lifetime_years
            roi_pct = (total_benefit / install_cost * 100) if install_cost > 0 else 0

            return {
                "battery_kwh": battery_kwh,
                "install_cost_usd": install_cost,
                "annual_utility_savings_usd": round(annual_utility_savings_usd, 2),
                "annual_peak_savings_kwh": round(annual_peak_savings_kwh, 2),
                "annual_peak_savings_usd": round(annual_peak_savings_usd, 2),
                "annual_self_consumption_benefit_usd": round(self_consumption_benefit_usd, 2),
                "annual_battery_cost_usd": round(annual_battery_cost_usd, 2),
                "annual_net_benefit_usd": round(annual_net_benefit_usd, 2),
                "payback_years": round(payback_years, 1) if payback_years < 100 else None,
                "roi_pct": round(roi_pct, 1),
                "system_lifetime_years": system_lifetime_years,
                "assumptions": {
                    "blended_rate_per_kwh": blended_rate,
                    "peak_rate_per_kwh": peak_rate,
                    "battery_efficiency_pct": battery_efficiency * 100,
                    "peak_shave_pct": peak_shave_pct * 100,
                    "annual_maintenance_usd": annual_maintenance,
                }
            }
    except Exception as e:
        log.warning("Failed to calculate Powerwall ROI: %s", e)
        return None


def get_recent_daily_trends(days=30):
    """
    Fetch recent daily energy data for dashboard visualization.
    """
    try:
        with _db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            cutoff = int(time.time()) - days * 86400

            c.execute("""
                SELECT
                    datetime(date_start, 'unixepoch') as date,
                    solar_kwh,
                    load_kwh,
                    grid_import_kwh,
                    grid_export_kwh,
                    battery_discharge_kwh,
                    battery_charge_kwh,
                    ct_charge_kwh,
                    peak_load_w,
                    avg_load_w,
                    self_powered_pct,
                    grid_cost_est
                FROM energy_daily
                WHERE date_start >= ?
                ORDER BY date_start ASC
            """, (cutoff,))

            rows = c.fetchall()
            conn.close()

            trends = []
            for row in rows:
                trends.append({
                    "date": row[0],
                    "solar_kwh": round(row[1] or 0, 2),
                    "load_kwh": round(row[2] or 0, 2),
                    "grid_import_kwh": round(row[3] or 0, 2),
                    "grid_export_kwh": round(row[4] or 0, 2),
                    "battery_discharge_kwh": round(row[5] or 0, 2),
                    "battery_charge_kwh": round(row[6] or 0, 2),
                    "ct_charge_kwh": round(row[7] or 0, 2),
                    "peak_load_w": round(row[8] or 0, 0),
                    "avg_load_w": round(row[9] or 0, 0),
                    "self_powered_pct": round(row[10] or 0, 1),
                    "grid_cost_est": round(row[11] or 0, 2),
                })

            return trends
    except Exception as e:
        log.warning("Failed to fetch daily trends: %s", e)
        return []

-- Energy Analytics — Common SQL Queries
-- Queen Creek Home Energy System
-- Last updated: 2026-03-01

-- ═════════════════════════════════════════════════════════════════════════════
-- DAILY SUMMARIES
-- ═════════════════════════════════════════════════════════════════════════════

-- Last 30 days of daily energy summary
SELECT
    datetime(date_start, 'unixepoch') as date,
    ROUND(solar_kwh, 2) as solar_kwh,
    ROUND(load_kwh, 2) as home_load_kwh,
    ROUND(grid_import_kwh, 2) as grid_import_kwh,
    ROUND(grid_export_kwh, 2) as grid_export_kwh,
    ROUND(self_powered_pct, 1) as self_powered_pct,
    ROUND(grid_cost_est, 2) as grid_cost_usd,
    ROUND(solar_kwh - grid_export_kwh, 2) as solar_used_kwh
FROM energy_daily
WHERE date_start >= strftime('%s', datetime('now', '-30 days'))
ORDER BY date_start DESC;

-- ═════════════════════════════════════════════════════════════════════════════
-- WEEKLY PATTERNS
-- ═════════════════════════════════════════════════════════════════════════════

-- Weekly totals: solar vs load trend
SELECT
    CAST(strftime('%W', datetime(date_start, 'unixepoch')) AS INTEGER) as week,
    CAST(strftime('%Y', datetime(date_start, 'unixepoch')) AS INTEGER) as year,
    ROUND(SUM(solar_kwh), 1) as weekly_solar_kwh,
    ROUND(SUM(load_kwh), 1) as weekly_load_kwh,
    ROUND(SUM(grid_import_kwh), 1) as weekly_grid_import_kwh,
    ROUND(SUM(grid_export_kwh), 1) as weekly_grid_export_kwh,
    ROUND(SUM(grid_cost_est), 2) as weekly_grid_cost_usd,
    ROUND(AVG(self_powered_pct), 1) as avg_self_powered_pct
FROM energy_daily
WHERE date_start >= strftime('%s', datetime('now', '-13 weeks'))
GROUP BY year, week
ORDER BY year, week DESC;

-- ═════════════════════════════════════════════════════════════════════════════
-- HOURLY ANALYSIS
-- ═════════════════════════════════════════════════════════════════════════════

-- Peak hours of the day (last 7 days)
SELECT
    CAST(strftime('%H', datetime(hour_start, 'unixepoch')) AS INTEGER) as hour,
    ROUND(AVG(load_kwh), 2) as avg_load_kwh,
    ROUND(MAX(peak_load_w), 0) as max_peak_load_w,
    ROUND(AVG(peak_load_w), 0) as avg_peak_load_w,
    COUNT(*) as samples
FROM energy_hourly
WHERE hour_start >= strftime('%s', datetime('now', '-7 days'))
GROUP BY hour
ORDER BY max_peak_load_w DESC;

-- Hourly pattern by day of week (all data)
SELECT
    CAST(strftime('%H', datetime(hour_start, 'unixepoch')) AS INTEGER) as hour,
    CAST(strftime('%w', datetime(hour_start, 'unixepoch')) AS INTEGER) as day_of_week,
    ROUND(AVG(load_kwh), 2) as avg_load_kwh,
    ROUND(MAX(peak_load_w), 0) as peak_load_w,
    ROUND(AVG(solar_kwh), 2) as avg_solar_kwh
FROM energy_hourly
GROUP BY hour, day_of_week
ORDER BY day_of_week, hour;

-- ═════════════════════════════════════════════════════════════════════════════
-- SOLAR PRODUCTION ANALYSIS
-- ═════════════════════════════════════════════════════════════════════════════

-- Daily solar production statistics
SELECT
    ROUND(AVG(solar_kwh), 2) as avg_daily_solar_kwh,
    ROUND(MAX(solar_kwh), 2) as max_daily_solar_kwh,
    ROUND(MIN(solar_kwh), 2) as min_daily_solar_kwh,
    ROUND(STDDEV(solar_kwh), 2) as stddev_solar_kwh,
    COUNT(*) as days
FROM energy_daily
WHERE solar_kwh > 0;

-- Solar vs Load by hour (identify midday excess)
SELECT
    CAST(strftime('%H', datetime(hour_start, 'unixepoch')) AS INTEGER) as hour,
    ROUND(AVG(solar_kwh), 2) as avg_solar_kwh,
    ROUND(AVG(load_kwh), 2) as avg_load_kwh,
    ROUND(AVG(solar_kwh - load_kwh), 2) as avg_excess_deficit_kwh,
    ROUND(AVG(grid_export_kwh), 2) as avg_exported_kwh
FROM energy_hourly
GROUP BY hour
ORDER BY hour;

-- ═════════════════════════════════════════════════════════════════════════════
-- GRID INTERACTION ANALYSIS
-- ═════════════════════════════════════════════════════════════════════════════

-- Peak hour grid demand (6-9 PM analysis)
SELECT
    CAST(strftime('%H', datetime(hour_start, 'unixepoch')) AS INTEGER) as hour,
    ROUND(AVG(grid_import_kwh), 2) as avg_peak_import_kwh,
    ROUND(MAX(grid_import_kwh), 2) as max_import_kwh,
    COUNT(*) as samples
FROM energy_hourly
WHERE CAST(strftime('%H', datetime(hour_start, 'unixepoch')) AS INTEGER) IN (18, 19, 20)
GROUP BY hour
ORDER BY avg_peak_import_kwh DESC;

-- Annual grid cost estimate by month
SELECT
    CAST(strftime('%m', datetime(date_start, 'unixepoch')) AS INTEGER) as month,
    ROUND(SUM(grid_cost_est), 2) as monthly_cost_usd,
    ROUND(SUM(grid_import_kwh), 1) as monthly_import_kwh,
    ROUND(SUM(grid_cost_est) / NULLIF(SUM(grid_import_kwh), 0), 3) as avg_effective_rate_per_kwh
FROM energy_daily
WHERE date_start >= strftime('%s', datetime('now', '-365 days'))
GROUP BY month
ORDER BY month;

-- ═════════════════════════════════════════════════════════════════════════════
-- SELF-POWERED PERCENTAGE ANALYSIS
-- ═════════════════════════════════════════════════════════════════════════════

-- Days with highest/lowest self-powered percentage
SELECT
    datetime(date_start, 'unixepoch') as date,
    ROUND(self_powered_pct, 1) as self_powered_pct,
    ROUND(solar_kwh, 1) as solar_kwh,
    ROUND(load_kwh, 1) as load_kwh,
    ROUND(grid_import_kwh, 1) as grid_import_kwh
FROM energy_daily
WHERE date_start >= strftime('%s', datetime('now', '-30 days'))
ORDER BY self_powered_pct DESC;

-- Self-powered statistics by month
SELECT
    CAST(strftime('%m', datetime(date_start, 'unixepoch')) AS INTEGER) as month,
    ROUND(AVG(self_powered_pct), 1) as avg_self_powered_pct,
    ROUND(MIN(self_powered_pct), 1) as min_self_powered_pct,
    ROUND(MAX(self_powered_pct), 1) as max_self_powered_pct,
    COUNT(*) as days
FROM energy_daily
WHERE date_start >= strftime('%s', datetime('now', '-365 days'))
GROUP BY month
ORDER BY month;

-- ═════════════════════════════════════════════════════════════════════════════
-- EV CHARGING ANALYSIS
-- ═════════════════════════════════════════════════════════════════════════════

-- Daily EV charging consumption
SELECT
    datetime(date_start, 'unixepoch') as date,
    ROUND(ct_charge_kwh, 2) as ct_charge_kwh,
    ROUND(load_kwh - ct_charge_kwh, 2) as home_only_kwh,
    ROUND(ct_charge_kwh / NULLIF(load_kwh, 0) * 100, 1) as pct_of_total_load
FROM energy_daily
WHERE ct_charge_kwh > 0.5
ORDER BY date DESC;

-- Monthly EV charging totals
SELECT
    CAST(strftime('%m', datetime(date_start, 'unixepoch')) AS INTEGER) as month,
    ROUND(SUM(ct_charge_kwh), 1) as monthly_ev_kwh,
    ROUND(SUM(load_kwh) - SUM(ct_charge_kwh), 1) as monthly_home_kwh,
    ROUND(SUM(ct_charge_kwh) / NULLIF(SUM(load_kwh), 0) * 100, 1) as pct_ev_of_total
FROM energy_daily
WHERE date_start >= strftime('%s', datetime('now', '-365 days'))
GROUP BY month
ORDER BY month DESC;

-- ═════════════════════════════════════════════════════════════════════════════
-- BATTERY SIMULATION (Future: with Powerwall)
-- ═════════════════════════════════════════════════════════════════════════════

-- Peak-shaving potential: grid imports during peak hours (6-9 PM)
SELECT
    ROUND(SUM(
        CASE
            WHEN CAST(strftime('%H', datetime(hour_start, 'unixepoch')) AS INTEGER) IN (18, 19, 20)
            AND grid_import_kwh > 0
            THEN grid_import_kwh
            ELSE 0
        END
    ), 1) as peak_hours_grid_import_kwh,
    ROUND(SUM(
        CASE
            WHEN CAST(strftime('%H', datetime(hour_start, 'unixepoch')) AS INTEGER) IN (18, 19, 20)
            AND grid_import_kwh > 0
            THEN grid_import_kwh * 0.23  -- Peak rate
            ELSE 0
        END
    ), 2) as peak_hours_cost_at_peak_rate_usd,
    ROUND(SUM(
        CASE
            WHEN CAST(strftime('%H', datetime(hour_start, 'unixepoch')) AS INTEGER) IN (18, 19, 20)
            AND grid_import_kwh > 0
            THEN grid_import_kwh * 0.18  -- Blended rate
            ELSE 0
        END
    ), 2) as peak_hours_cost_at_blended_rate_usd
FROM energy_hourly
WHERE hour_start >= strftime('%s', datetime('now', '-90 days'));

-- Off-peak available capacity (midnight-6 AM: ideal charging window)
SELECT
    ROUND(AVG(
        CASE
            WHEN CAST(strftime('%H', datetime(hour_start, 'unixepoch')) AS INTEGER) < 6
            THEN load_kwh
            ELSE 0
        END
    ), 2) as avg_night_load_kwh,
    ROUND(SUM(
        CASE
            WHEN CAST(strftime('%H', datetime(hour_start, 'unixepoch')) AS INTEGER) < 6
            THEN peak_load_w
            ELSE 0
        END
    ) / COUNT(DISTINCT CAST(strftime('%Y%m%d', datetime(hour_start, 'unixepoch')) AS TEXT)), 0) as avg_night_peak_w
FROM energy_hourly
WHERE hour_start >= strftime('%s', datetime('now', '-30 days'));

-- ═════════════════════════════════════════════════════════════════════════════
-- SYSTEM EFFICIENCY
-- ═════════════════════════════════════════════════════════════════════════════

-- Daily energy balance
SELECT
    datetime(date_start, 'unixepoch') as date,
    ROUND(solar_kwh, 2) as solar_generated_kwh,
    ROUND(grid_import_kwh, 2) as grid_import_kwh,
    ROUND(solar_kwh + grid_import_kwh, 2) as total_available_kwh,
    ROUND(load_kwh, 2) as load_kwh,
    ROUND(ct_charge_kwh, 2) as ev_kwh,
    ROUND(load_kwh + ct_charge_kwh, 2) as total_consumed_kwh,
    ROUND(grid_export_kwh, 2) as solar_export_kwh,
    ROUND((solar_kwh + grid_import_kwh) - (load_kwh + ct_charge_kwh + grid_export_kwh), 2) as unaccounted_kwh
FROM energy_daily
WHERE date_start >= strftime('%s', datetime('now', '-30 days'))
ORDER BY date_start DESC;

-- ═════════════════════════════════════════════════════════════════════════════
-- ANOMALY DETECTION
-- ═════════════════════════════════════════════════════════════════════════════

-- Days with unusual consumption patterns
WITH daily_stats AS (
    SELECT
        AVG(load_kwh) as avg_load,
        STDDEV(load_kwh) as stddev_load,
        AVG(peak_load_w) as avg_peak,
        STDDEV(peak_load_w) as stddev_peak
    FROM energy_daily
    WHERE date_start >= strftime('%s', datetime('now', '-90 days'))
)
SELECT
    datetime(d.date_start, 'unixepoch') as date,
    ROUND(d.load_kwh, 2) as load_kwh,
    ROUND(d.peak_load_w, 0) as peak_load_w,
    ROUND((d.load_kwh - s.avg_load) / NULLIF(s.stddev_load, 0), 2) as load_z_score,
    ROUND((d.peak_load_w - s.avg_peak) / NULLIF(s.stddev_peak, 0), 2) as peak_z_score
FROM energy_daily d
CROSS JOIN daily_stats s
WHERE d.date_start >= strftime('%s', datetime('now', '-30 days'))
AND ABS((d.load_kwh - s.avg_load) / NULLIF(s.stddev_load, 0)) > 2  -- > 2 std dev
ORDER BY load_z_score DESC;

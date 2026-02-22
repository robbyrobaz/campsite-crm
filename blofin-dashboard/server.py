#!/usr/bin/env python3
"""
Blofin Dashboard Server
Serves live ML trading pipeline metrics via REST API and static HTML dashboard.
"""

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
from flask import Flask, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Global response cache with TTL
_response_cache = {}
_cache_timestamps = {}

def cache_response(ttl_seconds=15):
    """Decorator to cache endpoint responses"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            cache_key = f.__name__
            now = time.time()
            if cache_key in _response_cache:
                if now - _cache_timestamps.get(cache_key, 0) < ttl_seconds:
                    return _response_cache[cache_key]
            result = f(*args, **kwargs)
            _response_cache[cache_key] = result
            _cache_timestamps[cache_key] = now
            return result
        return wrapper
    return decorator

# Configuration
DATA_DIR = Path("/home/rob/.openclaw/workspace/blofin-stack/data")
DB_PATH = DATA_DIR / "blofin_monitor.db"
REPORTS_DIR = DATA_DIR / "reports"
DASHBOARD_HTML = Path(__file__).parent / "blofin-dashboard.html"
STRATEGIES_DIR = Path("/home/rob/.openclaw/workspace/blofin-stack/strategies")

# Cache of strategy names that have a .py file (refresh every 60s)
_strategy_files_cache = None
_strategy_files_cache_ts = 0
_STRATEGY_FILES_TTL = 60


def get_strategy_file_names():
    """Return set of strategy names (stem of .py files) that exist on disk."""
    global _strategy_files_cache, _strategy_files_cache_ts
    now = time.time()
    if _strategy_files_cache is not None and now - _strategy_files_cache_ts < _STRATEGY_FILES_TTL:
        return _strategy_files_cache
    excluded = {'base_strategy', '__init__', 'strategy_promoter'}
    names = set()
    if STRATEGIES_DIR.exists():
        for p in STRATEGIES_DIR.glob('*.py'):
            stem = p.stem
            if stem not in excluded and not stem.startswith('__'):
                names.add(stem)
    _strategy_files_cache = names
    _strategy_files_cache_ts = now
    return names


def infer_tier_fallback(strategy_name, has_ft_data, has_bt_data):
    """Infer tier without strategy_registry: T2=forward-test data, T1=backtest only, T0=library."""
    if has_ft_data:
        return 2
    if has_bt_data:
        return 1
    return 0


def get_db_connection():
    """Get a database connection with proper settings."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def safe_query(query_func):
    """Decorator for safe database queries with error handling."""
    @wraps(query_func)
    def wrapper(*args, **kwargs):
        try:
            conn = get_db_connection()
            result = query_func(conn, *args, **kwargs)
            conn.close()
            return result
        except Exception as e:
            print(f"Database error in {query_func.__name__}: {e}")
            return jsonify({"error": str(e)}), 500
    return wrapper


def classify_leakage(train_acc, test_acc, f1_score=None):
    """Classify likely leakage using strict, near-perfect criteria to avoid false positives."""
    train = float(train_acc) if train_acc is not None else None
    test = float(test_acc) if test_acc is not None else None
    f1 = float(f1_score) if f1_score is not None else None

    # Only flag hard leakage when metrics are unrealistically near-perfect.
    if train is not None and test is not None:
        if train >= 0.99 and test >= 0.99:
            return True, f"Near-perfect train/test scores (train {train:.1%}, test {test:.1%}) — likely leakage"
        if f1 is not None and f1 >= 0.99 and test >= 0.99:
            return True, f"Near-perfect test F1/accuracy (F1 {f1:.1%}, test {test:.1%}) — likely leakage"
        return False, None

    # Missing OOS data is only suspicious when train score is essentially perfect.
    if train is not None and train >= 0.995:
        return True, "Train accuracy is near-perfect (≥99.5%) with no test/OOS data — verify split/feature pipeline"

    return False, None


@app.route('/')
def index():
    """Redirect to dashboard."""
    return send_file(DASHBOARD_HTML)


@app.route('/blofin-dashboard.html')
def dashboard():
    """Serve the dashboard HTML."""
    if not DASHBOARD_HTML.exists():
        return jsonify({"error": "Dashboard HTML not found"}), 404
    return send_file(DASHBOARD_HTML)


@app.route('/api/status')
@cache_response(ttl_seconds=15)
@safe_query
def api_status(conn):
    """Get current pipeline status (running/idle)."""
    cursor = conn.cursor()
    
    # Check recent heartbeats to determine if pipeline is running (LIMIT to 1000 recent rows)
    cursor.execute("""
        SELECT service, ts_iso, MAX(ts_ms) as latest_ts
        FROM (
            SELECT service, ts_iso, ts_ms 
            FROM service_heartbeats 
            ORDER BY ts_ms DESC 
            LIMIT 1000
        )
        GROUP BY service
        ORDER BY ts_ms DESC
    """)
    
    services = []
    now = datetime.utcnow()
    pipeline_running = False
    
    for row in cursor.fetchall():
        service_name = row['service']
        
        # Filter out old kanban services - they don't exist anymore
        if 'kanban' in service_name.lower():
            continue
            
        last_heartbeat = datetime.fromisoformat(row['ts_iso'].replace('Z', '+00:00'))
        age_seconds = (now - last_heartbeat.replace(tzinfo=None)).total_seconds()
        is_alive = age_seconds < 300  # Consider alive if heartbeat within 5 minutes
        
        services.append({
            "name": service_name,
            "last_heartbeat": row['ts_iso'],
            "age_seconds": int(age_seconds),
            "status": "running" if is_alive else "idle"
        })
        
        if is_alive:
            pipeline_running = True
    
    # Get latest activity counts
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM paper_trades
        WHERE opened_ts_iso > datetime('now', '-1 hour')
    """)
    recent_trades = cursor.fetchone()['count']
    
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM strategy_scores
        WHERE ts_iso > datetime('now', '-1 hour')
    """)
    recent_scores = cursor.fetchone()['count']
    
    return jsonify({
        "status": "running" if pipeline_running else "idle",
        "services": services,
        "activity": {
            "recent_trades_1h": recent_trades,
            "recent_scores_1h": recent_scores
        },
        "timestamp": datetime.utcnow().isoformat() + "Z"
    })


@app.route('/api/live-data')
@cache_response(ttl_seconds=5)
@safe_query
def api_live_data(conn):
    """Get real-time data flow status (lightweight, fast endpoint)."""
    cursor = conn.cursor()
    now = datetime.utcnow()
    
    # Recent ticks (last 10 seconds)
    ten_sec_ago = (now - timedelta(seconds=10)).isoformat()
    cursor.execute(
        "SELECT COUNT(*) as count FROM ticks WHERE ts_iso > ?",
        (ten_sec_ago,)
    )
    ticks_10s = cursor.fetchone()['count']
    
    # Recent signals (last 60 seconds)
    one_min_ago = (now - timedelta(seconds=60)).isoformat()
    cursor.execute(
        "SELECT COUNT(*) as count FROM signals WHERE ts_iso > ?",
        (one_min_ago,)
    )
    signals_1m = cursor.fetchone()['count']
    
    # Last tick timestamp
    cursor.execute(
        "SELECT MAX(ts_iso) as last_ts FROM ticks"
    )
    last_tick = cursor.fetchone()['last_ts']
    
    # Check if data is flowing (any ticks in last 30 seconds)
    thirty_sec_ago = (now - timedelta(seconds=30)).isoformat()
    cursor.execute(
        "SELECT COUNT(*) as count FROM ticks WHERE ts_iso > ?",
        (thirty_sec_ago,)
    )
    is_flowing = cursor.fetchone()['count'] > 0
    
    return jsonify({
        "ticks_10s": ticks_10s,
        "signals_1m": signals_1m,
        "last_tick_iso": last_tick,
        "is_flowing": is_flowing,
        "timestamp": now.isoformat() + "Z"
    })


@app.route('/api/strategies')
@cache_response(ttl_seconds=20)
@safe_query
def api_strategies(conn):
    """Get top strategies with scores and win rates. Filters out ghost strategies (no .py file)."""
    cursor = conn.cursor()
    valid_files = get_strategy_file_names()

    # Get top strategies from the last 24 hours
    cursor.execute("""
        SELECT
            strategy,
            MAX(score) as best_score,
            AVG(score) as avg_score,
            COUNT(*) as score_count,
            MAX(ts_iso) as last_update
        FROM strategy_scores
        WHERE ts_iso > datetime('now', '-24 hours')
        GROUP BY strategy
        ORDER BY best_score DESC
        LIMIT 20
    """)

    strategies = []
    for row in cursor.fetchall():
        # Skip ghost strategies (no .py file on disk)
        if row['strategy'] not in valid_files:
            continue
        strategies.append({
            "strategy": row['strategy'],
            "best_score": round(row['best_score'], 2) if row['best_score'] else 0,
            "avg_score": round(row['avg_score'], 2) if row['avg_score'] else 0,
            "score_count": row['score_count'],
            "last_update": row['last_update']
        })

    # Get strategy performance from live strategy_scores table (real backtested data)
    cursor.execute("""
        SELECT
            strategy,
            AVG(win_rate) as avg_win_rate,
            AVG(sharpe_ratio) as avg_sharpe,
            AVG(avg_pnl_pct) as avg_pnl,
            COUNT(*) as total_evals,
            MAX(ts_iso) as last_update
        FROM strategy_scores
        WHERE ts_iso > datetime('now', '-24 hours')
        GROUP BY strategy
        ORDER BY MAX(score) DESC
        LIMIT 20
    """)

    active_strategies = []
    for row in cursor.fetchall():
        if row['strategy'] not in valid_files:
            continue
        active_strategies.append({
            "name": row['strategy'],
            "win_rate": round(row['avg_win_rate'], 4) if row['avg_win_rate'] else 0,
            "sharpe_ratio": round(row['avg_sharpe'], 2) if row['avg_sharpe'] else 0,
            "total_pnl_pct": round(row['avg_pnl'], 2) if row['avg_pnl'] else 0,
            "trades": int(row['total_evals']) if row['total_evals'] else 0,
            "updated": row['last_update']
        })

    # Merge both arrays so dashboard gets complete data for each strategy
    merged_strategies = {}
    for s in strategies:
        merged_strategies[s['strategy']] = s
    for a in active_strategies:
        if a['name'] in merged_strategies:
            merged_strategies[a['name']].update({
                'win_rate': a['win_rate'],
                'sharpe_ratio': a['sharpe_ratio'],
                'total_pnl_pct': a['total_pnl_pct'],
                'trades': a['trades']
            })

    # Sort by: positive PNL first, then by Sharpe ratio, then by best_score
    merged_list = sorted(
        list(merged_strategies.values()),
        key=lambda x: (
            x.get('total_pnl_pct', 0) > 0,
            x.get('sharpe_ratio', 0),
            x.get('best_score', 0)
        ),
        reverse=True
    )

    return jsonify({
        "top_strategies": merged_list,
        "active_strategies": active_strategies,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    })


@app.route('/api/registry')
@cache_response(ttl_seconds=30)
@safe_query
def api_registry(conn):
    """
    Strategy registry endpoint.

    Returns per-strategy tier, backtest metrics, and forward-test metrics.
    If strategy_registry table exists: reads tier from it.
    Otherwise: infers tier from strategy_scores + strategy_backtest_results.
    Ghost strategies (no .py file on disk) are excluded.
    Also returns Tier 2 aggregate for headline metrics.
    """
    cursor = conn.cursor()
    valid_files = get_strategy_file_names()

    # Check if strategy_registry table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='strategy_registry'"
    )
    registry_exists = cursor.fetchone() is not None

    strategies = []

    if registry_exists:
        # Use strategy_registry as source of truth for tiers + metrics
        cursor.execute("""
            SELECT
                r.strategy_name,
                r.tier,
                r.file_path,
                r.strategy_type,
                r.source,
                r.description,
                r.bt_win_rate,
                r.bt_sharpe,
                r.bt_pnl_pct,
                r.bt_max_dd,
                r.bt_trades,
                r.bt_eep_score,
                r.bt_profit_factor,
                r.ft_win_rate,
                r.ft_sharpe,
                r.ft_pnl_pct,
                r.ft_max_dd,
                r.ft_trades,
                r.ft_eep_score,
                r.archived,
                r.archive_reason
            FROM strategy_registry r
            WHERE r.archived = 0
            ORDER BY COALESCE(r.ft_eep_score, r.bt_eep_score, 0) DESC
        """)
        for row in cursor.fetchall():
            name = row['strategy_name']
            has_file = name in valid_files
            bt_eep = float(row['bt_eep_score'] or 0)
            ft_eep = float(row['ft_eep_score'] or 0)
            eep_score = ft_eep if ft_eep else bt_eep
            strategies.append({
                "name": name,
                "tier": row['tier'],
                "has_file": has_file,
                "strategy_type": row['strategy_type'] or '',
                "source": row['source'] or 'registry',
                "description": row['description'] or '',
                "bt_win_rate": round(float(row['bt_win_rate'] or 0) * 100, 2),
                "bt_sharpe": round(float(row['bt_sharpe'] or 0), 3),
                "bt_pnl_pct": round(float(row['bt_pnl_pct'] or 0), 2),
                "bt_max_dd": round(float(row['bt_max_dd'] or 0), 2),
                "bt_trades": int(row['bt_trades'] or 0),
                "bt_eep_score": round(bt_eep, 2),
                "bt_profit_factor": round(float(row['bt_profit_factor'] or 0), 3) if row['bt_profit_factor'] else None,
                "ft_win_rate": round(float(row['ft_win_rate'] or 0) * 100, 2),
                "ft_sharpe": round(float(row['ft_sharpe'] or 0), 3),
                "ft_pnl_pct": round(float(row['ft_pnl_pct'] or 0), 2),
                "ft_max_dd": round(float(row['ft_max_dd'] or 0), 2),
                "ft_trades": int(row['ft_trades'] or 0),
                "ft_eep_score": round(ft_eep, 2),
                "eep_score": round(eep_score, 2),
            })
    else:
        # Fallback: build from strategy_scores + strategy_backtest_results
        # Fetch forward-test data from strategy_scores
        cursor.execute("""
            SELECT
                strategy,
                AVG(win_rate)          AS ft_win_rate,
                AVG(sharpe_ratio)      AS ft_sharpe,
                SUM(avg_pnl_pct * trades) / NULLIF(SUM(trades), 0) AS ft_pnl_pct,
                AVG(max_drawdown_pct)  AS ft_max_dd,
                SUM(trades)            AS ft_trades,
                MAX(score)             AS best_score
            FROM strategy_scores
            GROUP BY strategy
        """)
        ft_data = {}
        for row in cursor.fetchall():
            ft_data[row['strategy']] = dict(row)

        # Fetch backtest data from strategy_backtest_results
        cursor.execute("""
            SELECT
                strategy,
                win_rate  AS bt_win_rate,
                sharpe_ratio AS bt_sharpe,
                total_pnl_pct AS bt_pnl_pct,
                max_drawdown_pct AS bt_max_dd,
                total_trades AS bt_trades
            FROM strategy_backtest_results
            ORDER BY ts_iso DESC
        """)
        bt_data = {}
        for row in cursor.fetchall():
            name = row['strategy']
            if name not in bt_data:
                bt_data[name] = dict(row)

        all_names = set(list(ft_data.keys()) + list(bt_data.keys()))
        for name in sorted(all_names):
            if name not in valid_files:
                continue  # ghost strategy: skip
            ft = ft_data.get(name, {})
            bt = bt_data.get(name, {})
            has_ft = bool(ft)
            has_bt = bool(bt)
            tier = infer_tier_fallback(name, has_ft, has_bt)
            strategies.append({
                "name": name,
                "tier": tier,
                "has_file": True,
                "bt_win_rate": round(float(bt.get('bt_win_rate') or 0) * 100, 2),
                "bt_sharpe": round(float(bt.get('bt_sharpe') or 0), 3),
                "bt_pnl_pct": round(float(bt.get('bt_pnl_pct') or 0), 2),
                "bt_max_dd": round(float(bt.get('bt_max_dd') or 0), 2),
                "bt_trades": int(bt.get('bt_trades') or 0),
                "ft_win_rate": round(float(ft.get('ft_win_rate') or 0) * 100, 2),
                "ft_sharpe": round(float(ft.get('ft_sharpe') or 0), 3),
                "ft_pnl_pct": round(float(ft.get('ft_pnl_pct') or 0), 2),
                "ft_max_dd": round(float(ft.get('ft_max_dd') or 0), 2),
                "ft_trades": int(ft.get('ft_trades') or 0),
                "source": "fallback",
            })
        # Sort: T2 first, then by ft_pnl_pct
        strategies.sort(key=lambda s: (-s['tier'], -s['ft_pnl_pct']))

    # Compute Tier 2 aggregates for headline metrics
    t2 = [s for s in strategies if s['tier'] == 2]
    t2_count = len(t2)
    if t2_count > 0:
        t2_avg_wr = round(sum(s['ft_win_rate'] for s in t2) / t2_count, 2)
        t2_avg_sharpe = round(sum(s['ft_sharpe'] for s in t2) / t2_count, 3)
        t2_total_pnl = round(sum(s['ft_pnl_pct'] for s in t2), 2)
        t2_avg_dd = round(sum(s['ft_max_dd'] for s in t2) / t2_count, 2)
        t2_total_trades = sum(s['ft_trades'] for s in t2)
    else:
        t2_avg_wr = t2_avg_sharpe = t2_total_pnl = t2_avg_dd = 0
        t2_total_trades = 0

    return jsonify({
        "strategies": strategies,
        "count": len(strategies),
        "registry_exists": registry_exists,
        "tier2_summary": {
            "count": t2_count,
            "avg_win_rate": t2_avg_wr,
            "avg_sharpe": t2_avg_sharpe,
            "total_pnl_pct": t2_total_pnl,
            "avg_max_dd": t2_avg_dd,
            "total_trades": t2_total_trades,
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })


@app.route('/api/models')
@cache_response(ttl_seconds=20)
@safe_query
def api_models(conn):
    """Get ML models accuracy and performance."""
    cursor = conn.cursor()
    
    # P1 FIX: Top-N deduplication — GROUP BY model_name, return only latest row per model
    # Previously returned 100 rows with duplicates; now deduplicated at SQL level
    cursor.execute("""
        SELECT 
            m.model_name,
            m.train_accuracy,
            m.test_accuracy,
            m.precision_score,
            m.recall_score,
            m.f1_score,
            m.ts_iso
        FROM ml_model_results m
        INNER JOIN (
            SELECT model_name, MAX(ts_iso) AS latest_ts
            FROM ml_model_results
            WHERE archived = 0
            GROUP BY model_name
        ) latest ON m.model_name = latest.model_name AND m.ts_iso = latest.latest_ts
        ORDER BY m.ts_iso DESC
    """)
    
    models = []
    for row in cursor.fetchall():
        train_acc = row['train_accuracy']
        test_acc = row['test_accuracy']

        # Prefer out-of-sample (test) accuracy as primary metric
        accuracy = test_acc if test_acc is not None else train_acc

        leakage_flag, leakage_note = classify_leakage(
            train_acc,
            test_acc,
            row['f1_score'],
        )

        models.append({
            "model_name": row['model_name'],
            "accuracy": round(accuracy * 100, 2) if accuracy else 0,
            "train_accuracy": round(train_acc * 100, 2) if train_acc else 0,
            "test_accuracy": round(test_acc * 100, 2) if test_acc else 0,
            "precision": round(row['precision_score'] * 100, 2) if row['precision_score'] else 0,
            "recall": round(row['recall_score'] * 100, 2) if row['recall_score'] else 0,
            "f1_score": round(row['f1_score'], 3) if row['f1_score'] else 0,
            "leakage_flag": leakage_flag,
            "leakage_note": leakage_note,
            "created_at": row['ts_iso']
        })
    
    # Get model performance over time for charting
    cursor.execute("""
        SELECT 
            model_name,
            train_accuracy,
            ts_iso
        FROM ml_model_results
        WHERE archived = 0 
          AND train_accuracy IS NOT NULL
        ORDER BY ts_iso ASC
    """)
    
    model_history = []
    for row in cursor.fetchall():
        model_history.append({
            "model_name": row['model_name'],
            "accuracy": round(row['train_accuracy'] * 100, 2),
            "timestamp": row['ts_iso']
        })
    
    # Get ensemble results
    cursor.execute("""
        SELECT 
            ensemble_name,
            test_accuracy,
            ts_iso
        FROM ml_ensembles
        WHERE archived = 0
        ORDER BY ts_iso DESC
        LIMIT 20
    """)
    
    ensembles = []
    for row in cursor.fetchall():
        ensembles.append({
            "name": row['ensemble_name'],
            "accuracy": round(row['test_accuracy'] * 100, 2) if row['test_accuracy'] else 0,
            "created_at": row['ts_iso']
        })
    
    return jsonify({
        "models": models,
        "ensembles": ensembles,
        "model_history": model_history,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    })


@app.route('/api/reports')
@cache_response(ttl_seconds=30)
@safe_query
def api_reports(conn):
    """Get latest hourly/daily reports."""
    cursor = conn.cursor()
    
    # Get the latest DAILY report from filesystem
    # P4 FIX: Only match date-pattern files (YYYY-MM-DD.json), not optimizer_results files
    latest_report_file = None
    if REPORTS_DIR.exists():
        import re as _re
        date_pattern = _re.compile(r'^\d{4}-\d{2}-\d{2}\.json$')
        report_files = sorted(
            [f for f in REPORTS_DIR.glob("*.json") if date_pattern.match(f.name)],
            reverse=True
        )
        if report_files:
            latest_report_file = report_files[0]
    
    latest_report = None
    if latest_report_file and latest_report_file.exists():
        try:
            with open(latest_report_file, 'r') as f:
                latest_report = json.load(f)
        except Exception as e:
            print(f"Error reading report file: {e}")
    
    # Get recent reports from database
    cursor.execute("""
        SELECT 
            date,
            full_report_json,
            summary
        FROM daily_reports
        ORDER BY date DESC
        LIMIT 7
    """)
    
    db_reports = []
    for row in cursor.fetchall():
        try:
            report_data = json.loads(row['full_report_json']) if row['full_report_json'] else {}
            db_reports.append({
                "date": row['date'],
                "summary": row['summary'],
                "data": report_data
            })
        except json.JSONDecodeError:
            continue
    
    return jsonify({
        "latest_report": latest_report,
        "recent_reports": db_reports,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    })


@app.route('/api/advanced_metrics')
@cache_response(ttl_seconds=20)
@safe_query
def api_advanced_metrics(conn):
    """Get advanced trading and ML metrics."""
    cursor = conn.cursor()
    
    # Calculate detailed trading metrics from closed trades
    cursor.execute("""
        SELECT 
            COUNT(*) as total_trades,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as winning_trades,
            SUM(CASE WHEN pnl_pct < 0 THEN 1 ELSE 0 END) as losing_trades,
            AVG(pnl_pct) as avg_pnl,
            AVG(CASE WHEN pnl_pct > 0 THEN pnl_pct ELSE NULL END) as avg_win,
            AVG(CASE WHEN pnl_pct < 0 THEN pnl_pct ELSE NULL END) as avg_loss,
            MAX(pnl_pct) as max_win,
            MIN(pnl_pct) as max_loss,
            SUM(pnl_pct) as total_pnl
        FROM paper_trades
        WHERE status = 'CLOSED' AND pnl_pct IS NOT NULL
    """)
    
    trade_stats = cursor.fetchone()
    
    # Calculate profit factor
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN pnl_pct > 0 THEN pnl_pct ELSE 0 END) as total_profit,
            ABS(SUM(CASE WHEN pnl_pct < 0 THEN pnl_pct ELSE 0 END)) as total_loss
        FROM paper_trades
        WHERE status = 'CLOSED' AND pnl_pct IS NOT NULL
    """)
    pf_data = cursor.fetchone()
    profit_factor = (pf_data['total_profit'] / pf_data['total_loss']) if pf_data['total_loss'] > 0 else 0
    
    # Get strategy performance metrics
    cursor.execute("""
        SELECT 
            AVG(sharpe_ratio) as avg_sharpe,
            MAX(sharpe_ratio) as max_sharpe,
            AVG(max_drawdown_pct) as avg_drawdown,
            MAX(max_drawdown_pct) as max_drawdown,
            AVG(win_rate) as avg_win_rate,
            AVG(score) as avg_score
        FROM strategy_scores
        WHERE ts_iso > datetime('now', '-7 days')
    """)
    
    strat_metrics = cursor.fetchone()
    
    # Calculate Sortino ratio (simplified - using downside deviation)
    cursor.execute("""
        SELECT 
            AVG(pnl_pct) as mean_return,
            AVG(CASE WHEN pnl_pct < 0 THEN pnl_pct * pnl_pct ELSE 0 END) as downside_var
        FROM paper_trades
        WHERE status = 'CLOSED' AND pnl_pct IS NOT NULL
    """)
    sortino_data = cursor.fetchone()
    downside_std = (sortino_data['downside_var'] ** 0.5) if sortino_data['downside_var'] else 0
    sortino_ratio = (sortino_data['mean_return'] / downside_std) if downside_std > 0 else 0
    
    # Win rate
    win_rate = (trade_stats['winning_trades'] / trade_stats['total_trades'] * 100) if trade_stats['total_trades'] > 0 else 0
    
    # Expectancy
    expectancy = trade_stats['avg_pnl'] if trade_stats['avg_pnl'] else 0
    
    # Top 3 strategies by score — used for headline metrics
    cursor.execute("""
        SELECT strategy, MAX(score) as score, 
               AVG(win_rate) as win_rate, AVG(sharpe_ratio) as sharpe_ratio, 
               AVG(max_drawdown_pct) as max_drawdown_pct,
               AVG(avg_pnl_pct) as avg_pnl_pct, AVG(total_pnl_pct) as total_pnl_pct, 
               AVG(trades) as trades
        FROM strategy_scores
        WHERE ts_iso > datetime('now', '-7 days')
        GROUP BY strategy
        ORDER BY score DESC
        LIMIT 3
    """)
    top3 = cursor.fetchall()

    top3_info = []
    t3_wr_sum = 0; t3_sharpe_sum = 0; t3_dd_sum = 0; t3_pnl_sum = 0; t3_exp_sum = 0; t3_trades_sum = 0
    for r in (top3 or []):
        wr = round((r['win_rate'] or 0) * 100, 1)
        sharpe = round(r['sharpe_ratio'] or 0, 2)
        dd = round(r['max_drawdown_pct'] or 0, 1)
        pnl = round(r['total_pnl_pct'] or 0, 2)
        exp = round(r['avg_pnl_pct'] or 0, 4)
        trades = r['trades'] or 0
        top3_info.append({
            "strategy": r['strategy'],
            "score": round(r['score'], 1),
            "win_rate": wr, "sharpe": sharpe, "max_dd": dd
        })
        t3_wr_sum += wr; t3_sharpe_sum += sharpe; t3_dd_sum += dd
        t3_pnl_sum += pnl; t3_exp_sum += exp; t3_trades_sum += trades
    
    n = max(len(top3 or []), 1)

    return jsonify({
        "trading_metrics": {
            "total_trades": trade_stats['total_trades'] or 0,
            "winning_trades": trade_stats['winning_trades'] or 0,
            "losing_trades": trade_stats['losing_trades'] or 0,
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 3),
            "expectancy": round(expectancy, 4),
            "avg_win": round(trade_stats['avg_win'] or 0, 4),
            "avg_loss": round(trade_stats['avg_loss'] or 0, 4),
            "max_win": round(trade_stats['max_win'] or 0, 4),
            "max_loss": round(trade_stats['max_loss'] or 0, 4),
            "total_pnl_pct": round(trade_stats['total_pnl'] or 0, 2)
        },
        "risk_metrics": {
            "sortino_ratio": round(sortino_ratio, 3),
            "avg_sharpe_ratio": round(strat_metrics['avg_sharpe'] or 0, 3),
            "max_sharpe_ratio": round(strat_metrics['max_sharpe'] or 0, 3),
            "avg_drawdown_pct": round(strat_metrics['avg_drawdown'] or 0, 2),
            "max_drawdown_pct": round(strat_metrics['max_drawdown'] or 0, 2)
        },
        "strategy_metrics": {
            "avg_strategy_score": round(strat_metrics['avg_score'] or 0, 2),
            "avg_strategy_win_rate": round((strat_metrics['avg_win_rate'] or 0) * 100, 2)
        },
        "top3_metrics": {
            "strategies": top3_info,
            "profit_factor": 0,
            "win_rate": round(t3_wr_sum / n, 2),
            "total_pnl_pct": round(t3_pnl_sum, 2),
            "expectancy": round(t3_exp_sum / n, 4),
            "total_trades": t3_trades_sum,
            "avg_sharpe": round(t3_sharpe_sum / n, 3),
            "avg_max_dd": round(t3_dd_sum / n, 2)
        },
        "timestamp": datetime.utcnow().isoformat() + "Z"
    })


@app.route('/api/backtest-comparison')
@cache_response(ttl_seconds=30)
@safe_query
def api_backtest_comparison(conn):
    """
    Backtest vs Paper Trading comparison endpoint.
    
    Returns per-strategy metrics from:
    - strategy_backtest_results (historical backtest)
    - strategy_scores + paper_trades (live paper trading reality)
    
    Includes convergence analysis and performance delta.
    """
    cursor = conn.cursor()
    
    # ─── 1. Fetch backtest results ─────────────────────────────────────────
    cursor.execute("""
        SELECT strategy, symbol, win_rate, sharpe_ratio,
               max_drawdown_pct, total_pnl_pct, total_trades,
               ts_iso, status
        FROM strategy_backtest_results
        ORDER BY ts_iso DESC
    """)
    backtest_rows = {}
    for row in cursor.fetchall():
        key = row['strategy']
        if key not in backtest_rows:
            backtest_rows[key] = dict(row)
    
    # ─── 2. Fetch optimizer top strategies (most recent run) ──────────────
    cursor.execute("SELECT raw_json FROM optimizer_runs ORDER BY ts_iso DESC LIMIT 1")
    opt_row = cursor.fetchone()
    if opt_row and opt_row['raw_json']:
        try:
            opt_data = json.loads(opt_row['raw_json'])
            for s in opt_data.get('top_strategies', []):
                key = s.get('strategy', 'unknown')
                if key not in backtest_rows:
                    backtest_rows[key] = {
                        'strategy': key,
                        'symbol': s.get('symbol', ''),
                        'win_rate': float(s.get('win_rate', 0)),
                        'sharpe_ratio': float(s.get('sharpe_ratio', 0)),
                        'max_drawdown_pct': float(s.get('max_drawdown_pct', 0)),
                        'total_pnl_pct': float(s.get('total_pnl_pct', 0)),
                        'total_trades': int(s.get('num_trades', 0)),
                        'ts_iso': opt_data.get('run_timestamp', ''),
                        'status': 'optimizer',
                    }
        except Exception as e:
            print(f"Error parsing optimizer_runs: {e}")
    
    # ─── 3. Fetch paper trading metrics per strategy ───────────────────────
    cursor.execute("""
        SELECT 
            ss.strategy,
            AVG(ss.win_rate)           AS paper_win_rate,
            AVG(ss.sharpe_ratio)       AS paper_sharpe,
            AVG(ss.max_drawdown_pct)   AS paper_max_dd,
            AVG(ss.avg_pnl_pct)        AS paper_avg_pnl,
            SUM(ss.trades)             AS paper_total_trades,
            MAX(ss.ts_iso)             AS last_updated,
            COUNT(*)                   AS eval_count
        FROM strategy_scores ss
        GROUP BY ss.strategy
        ORDER BY last_updated DESC
    """)
    paper_rows = {}
    for row in cursor.fetchall():
        paper_rows[row['strategy']] = dict(row)
    
    # ─── 4. Fetch paper trade PnL aggregates ──────────────────────────────
    # paper_trades doesn't have strategy column, so use confirmed_signals join
    cursor.execute("""
        SELECT 
            COUNT(*)                                        AS total_closed,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END)  AS winning_trades,
            AVG(pnl_pct)                                    AS avg_pnl_pct,
            SUM(pnl_pct)                                    AS total_pnl_pct
        FROM paper_trades
        WHERE status = 'CLOSED' AND pnl_pct IS NOT NULL
    """)
    global_paper = dict(cursor.fetchone())
    global_paper_wr = (
        global_paper['winning_trades'] / global_paper['total_closed'] * 100
        if global_paper['total_closed'] > 0 else 0
    )
    
    # ─── 5. Build comparison per strategy ────────────────────────────────
    strategies = []
    all_keys = set(list(backtest_rows.keys()) + list(paper_rows.keys()))
    
    for key in sorted(all_keys):
        bt = backtest_rows.get(key, {})
        pt = paper_rows.get(key, {})
        
        if not bt and not pt:
            continue
        
        # Backtest metrics (from historical simulation)
        bt_win_rate = float(bt.get('win_rate', 0) or 0)
        bt_sharpe   = float(bt.get('sharpe_ratio', 0) or 0)
        bt_mdd      = float(bt.get('max_drawdown_pct', 0) or 0)
        bt_pnl      = float(bt.get('total_pnl_pct', 0) or 0)
        bt_trades   = int(bt.get('total_trades', 0) or 0)
        
        # Paper trading metrics (from live strategy scoring)
        pt_win_rate = float(pt.get('paper_win_rate', 0) or 0) if pt else 0
        pt_sharpe   = float(pt.get('paper_sharpe', 0) or 0) if pt else 0
        pt_mdd      = float(pt.get('paper_max_dd', 0) or 0) if pt else 0
        pt_pnl      = float(pt.get('paper_avg_pnl', 0) or 0) * float(pt.get('paper_total_trades', 1) or 1) if pt else 0
        pt_trades   = int(pt.get('paper_total_trades', 0) or 0) if pt else 0
        pt_evals    = int(pt.get('eval_count', 0) or 0) if pt else 0
        
        # ── P5: Convergence gates ──────────────────────────────────────────
        # Convergence = how close paper trading is to backtest expectations
        # Score: 0% = completely diverged, 100% = converged
        convergence_score = None
        convergence_status = "INSUFFICIENT_DATA"
        auto_archive = False
        
        if bt and pt and pt_trades >= 30:
            # Win rate convergence (within 15% = converging)
            wr_diff = abs(bt_win_rate - pt_win_rate)
            wr_conv = max(0, 1.0 - (wr_diff / max(bt_win_rate, 0.01)))
            
            # PnL direction convergence (same sign = good)
            pnl_same_dir = (bt_pnl >= 0 and pt_pnl >= 0) or (bt_pnl < 0 and pt_pnl < 0)
            pnl_conv = 1.0 if pnl_same_dir else 0.0
            
            # Sharpe convergence (within 1.0 = acceptable)
            sharpe_diff = abs(bt_sharpe - pt_sharpe)
            sharpe_conv = max(0, 1.0 - (sharpe_diff / max(abs(bt_sharpe), 0.1)))
            
            convergence_score = round((wr_conv * 0.4 + pnl_conv * 0.4 + sharpe_conv * 0.2) * 100, 1)
            
            if convergence_score >= 70:
                convergence_status = "CONVERGING"
            elif convergence_score >= 40:
                convergence_status = "DIVERGING"
            else:
                convergence_status = "DIVERGED"
                # P5 Auto-archive: if severely diverged and enough data
                if pt_trades >= 100 and bt_pnl > 0 and pt_pnl < -10:
                    auto_archive = True
        
        # ── Performance deltas ────────────────────────────────────────────
        strategies.append({
            "strategy": key,
            "symbol": bt.get('symbol', '') or '',
            "status": bt.get('status', 'unknown'),
            "backtest": {
                "win_rate_pct": round(bt_win_rate * 100, 2),
                "sharpe_ratio": round(bt_sharpe, 3),
                "max_drawdown_pct": round(bt_mdd, 2),
                "total_pnl_pct": round(bt_pnl, 2),
                "total_trades": bt_trades,
                "has_data": bool(bt),
            },
            "paper": {
                "win_rate_pct": round(pt_win_rate * 100, 2),
                "sharpe_ratio": round(pt_sharpe, 3),
                "max_drawdown_pct": round(pt_mdd, 2),
                "total_pnl_pct": round(pt_pnl, 2),
                "total_trades": pt_trades,
                "eval_count": pt_evals,
                "has_data": bool(pt),
            },
            "delta": {
                "win_rate_delta_pct": round((pt_win_rate - bt_win_rate) * 100, 2),
                "sharpe_delta": round(pt_sharpe - bt_sharpe, 3),
                "mdd_delta_pct": round(pt_mdd - bt_mdd, 2),
                "pnl_delta_pct": round(pt_pnl - bt_pnl, 2),
            },
            "convergence": {
                "score": convergence_score,
                "status": convergence_status,
                "auto_archive_recommended": auto_archive,
            },
        })
    
    # Sort: converging first, then by backtest PnL
    def sort_key(s):
        conv = {"CONVERGING": 0, "DIVERGING": 1, "DIVERGED": 2, "INSUFFICIENT_DATA": 3}
        return (conv.get(s["convergence"]["status"], 3), -s["backtest"]["total_pnl_pct"])
    
    strategies.sort(key=sort_key)
    
    # Global paper stats
    return jsonify({
        "strategies": strategies,
        "count": len(strategies),
        "global_paper": {
            "total_closed_trades": global_paper.get('total_closed', 0),
            "win_rate_pct": round(global_paper_wr, 2),
            "avg_pnl_pct": round(global_paper.get('avg_pnl_pct', 0) or 0, 4),
            "total_pnl_pct": round(global_paper.get('total_pnl_pct', 0) or 0, 2),
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })


@app.route('/api/ml_models')
@cache_response(ttl_seconds=30)
@safe_query
def api_ml_models(conn):
    """
    ML model results with leakage detection.
    Returns latest row per model_name, ordered by best accuracy.
    """
    cursor = conn.cursor()
    # Deduplicate: get latest row per model_name
    cursor.execute("""
        SELECT m.model_name, m.model_type, m.symbol,
               m.train_accuracy, m.test_accuracy,
               m.f1_score, m.precision_score, m.recall_score, m.roc_auc,
               m.ts_iso, m.archived
        FROM ml_model_results m
        INNER JOIN (
            SELECT model_name, MAX(ts_iso) AS latest_ts
            FROM ml_model_results
            WHERE archived = 0
            GROUP BY model_name
        ) latest ON m.model_name = latest.model_name AND m.ts_iso = latest.latest_ts
        ORDER BY COALESCE(m.test_accuracy, m.train_accuracy, 0) DESC
    """)
    models = []
    for row in cursor.fetchall():
        train_acc = row['train_accuracy'] or 0
        test_acc = row['test_accuracy']
        leakage_suspected, leakage_note = classify_leakage(
            train_acc,
            test_acc,
            row['f1_score'],
        )
        models.append({
            "model_name": row['model_name'],
            "model_type": row['model_type'] or 'unknown',
            "symbol": row['symbol'] or '',
            "train_accuracy": round(train_acc * 100, 2),
            "test_accuracy": round(test_acc * 100, 2) if test_acc is not None else None,
            "f1_score": round(row['f1_score'], 4) if row['f1_score'] else None,
            "precision": round(row['precision_score'] * 100, 2) if row['precision_score'] else None,
            "recall": round(row['recall_score'] * 100, 2) if row['recall_score'] else None,
            "roc_auc": round(row['roc_auc'], 4) if row['roc_auc'] else None,
            "leakage_suspected": leakage_suspected,
            "leakage_note": leakage_note,
            "last_trained": row['ts_iso'],
        })
    return jsonify({
        "models": models,
        "count": len(models),
        "leakage_count": sum(1 for m in models if m['leakage_suspected']),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })


@app.route('/api/summary')
@cache_response(ttl_seconds=15)
@safe_query
def api_summary(conn):
    """
    Live data summary: signals, paper trade stats, tick rate.
    Replaces proxy to deprecated port 8780.
    """
    cursor = conn.cursor()
    now = datetime.utcnow()

    # Total signal count
    cursor.execute("SELECT COUNT(*) as cnt FROM signals")
    signals_count = cursor.fetchone()['cnt']

    # Recent signals (last 20)
    cursor.execute("""
        SELECT ts_iso, symbol, signal, strategy, confidence, price
        FROM signals
        ORDER BY ts_ms DESC
        LIMIT 20
    """)
    recent_signals = [dict(row) for row in cursor.fetchall()]

    # Signal breakdown last 1h
    one_hour_ago = (now - timedelta(hours=1)).isoformat()
    cursor.execute("""
        SELECT signal, COUNT(*) as cnt
        FROM signals
        WHERE ts_iso > ?
        GROUP BY signal
    """, (one_hour_ago,))
    signals_1h_by_type = {row['signal']: row['cnt'] for row in cursor.fetchall()}

    # Paper trade stats
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END) as closed,
            SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) as open_count,
            SUM(CASE WHEN status = 'CLOSED' AND pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
            AVG(CASE WHEN status = 'CLOSED' AND pnl_pct IS NOT NULL THEN pnl_pct END) as avg_pnl,
            SUM(CASE WHEN status = 'CLOSED' AND pnl_pct > 0 THEN pnl_pct ELSE 0 END) as gross_profit,
            ABS(SUM(CASE WHEN status = 'CLOSED' AND pnl_pct < 0 THEN pnl_pct ELSE 0 END)) as gross_loss
        FROM paper_trades
    """)
    pt = cursor.fetchone()
    closed = pt['closed'] or 0
    wins = pt['wins'] or 0
    gross_profit = pt['gross_profit'] or 0
    gross_loss = pt['gross_loss'] or 0
    profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else 0

    # Recent paper trades
    cursor.execute("""
        SELECT opened_ts_iso, closed_ts_iso, symbol, side, entry_price, exit_price,
               status, pnl_pct
        FROM paper_trades
        ORDER BY id DESC
        LIMIT 15
    """)
    recent_trades = [dict(row) for row in cursor.fetchall()]

    # Live data flow
    ten_sec_ago = (now - timedelta(seconds=10)).isoformat()
    thirty_sec_ago = (now - timedelta(seconds=30)).isoformat()
    cursor.execute("SELECT COUNT(*) as cnt FROM ticks WHERE ts_iso > ?", (ten_sec_ago,))
    ticks_10s = cursor.fetchone()['cnt']
    cursor.execute("SELECT COUNT(*) as cnt FROM ticks WHERE ts_iso > ?", (thirty_sec_ago,))
    ticks_30s = cursor.fetchone()['cnt']
    cursor.execute("SELECT MAX(ts_iso) as last_ts FROM ticks")
    last_tick_row = cursor.fetchone()
    last_tick_iso = last_tick_row['last_ts'] if last_tick_row else None

    is_live = ticks_10s > 2

    # Service heartbeats
    cursor.execute("""
        SELECT service, MAX(ts_iso) as last_ts
        FROM (SELECT service, ts_iso FROM service_heartbeats ORDER BY ts_ms DESC LIMIT 1000)
        GROUP BY service
    """)
    services = []
    for row in cursor.fetchall():
        try:
            last_hb = datetime.fromisoformat(row['last_ts'].replace('Z', '+00:00'))
            age_s = (now - last_hb.replace(tzinfo=None)).total_seconds()
            services.append({
                "name": row['service'],
                "last_ts": row['last_ts'],
                "age_seconds": int(age_s),
                "alive": age_s < 300,
            })
        except Exception:
            pass

    return jsonify({
        "signals_count": signals_count,
        "signals_1h_by_type": signals_1h_by_type,
        "recent_signals": recent_signals,
        "paper_stats": {
            "total": pt['total'] or 0,
            "closed": closed,
            "open_count": pt['open_count'] or 0,
            "win_rate_pct": round(wins / closed * 100, 2) if closed > 0 else 0,
            "avg_pnl_pct": round(pt['avg_pnl'] or 0, 4),
            "profit_factor": profit_factor,
        },
        "recent_trades": recent_trades,
        "live_status": {
            "is_live": is_live,
            "ticks_10s": ticks_10s,
            "ticks_30s": ticks_30s,
            "last_tick_iso": last_tick_iso,
            "tick_rate_per_sec": round(ticks_10s / 10, 1),
        },
        "services": services,
        "timestamp": now.isoformat() + "Z",
    })


@app.route('/health')
def health():
    """Health check endpoint."""
    db_accessible = DB_PATH.exists()
    return jsonify({
        "status": "healthy" if db_accessible else "degraded",
        "database": "accessible" if db_accessible else "not found",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    })


if __name__ == '__main__':
    print(f"Starting Blofin Dashboard Server on http://localhost:8888")
    print(f"Database: {DB_PATH}")
    print(f"Dashboard: http://localhost:8888/blofin-dashboard.html")
    app.run(host='0.0.0.0', port=8888, debug=False)

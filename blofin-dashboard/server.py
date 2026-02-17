#!/usr/bin/env python3
"""
Blofin Dashboard Server
Serves live ML trading pipeline metrics via REST API and static HTML dashboard.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
from flask import Flask, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Configuration
DATA_DIR = Path("/home/rob/.openclaw/workspace/blofin-stack/data")
DB_PATH = DATA_DIR / "blofin_monitor.db"
REPORTS_DIR = DATA_DIR / "reports"
DASHBOARD_HTML = Path(__file__).parent / "blofin-dashboard.html"


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
@safe_query
def api_status(conn):
    """Get current pipeline status (running/idle)."""
    cursor = conn.cursor()
    
    # Check recent heartbeats to determine if pipeline is running
    cursor.execute("""
        SELECT service, ts_iso, MAX(ts_ms) as latest_ts
        FROM service_heartbeats
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


@app.route('/api/strategies')
@safe_query
def api_strategies(conn):
    """Get top strategies with scores and win rates."""
    cursor = conn.cursor()
    
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
        active_strategies.append({
            "name": row['strategy'],
            "win_rate": round(row['avg_win_rate'] * 100, 1) if row['avg_win_rate'] else 0,
            "sharpe_ratio": round(row['avg_sharpe'], 2) if row['avg_sharpe'] else 0,
            "total_pnl_pct": round(row['avg_pnl'], 2) if row['avg_pnl'] else 0,
            "trades": int(row['total_evals']) if row['total_evals'] else 0,
            "updated": row['last_update']
        })
    
    return jsonify({
        "top_strategies": strategies,
        "active_strategies": active_strategies,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    })


@app.route('/api/models')
@safe_query
def api_models(conn):
    """Get ML models accuracy and performance."""
    cursor = conn.cursor()
    
    # Get recent ML model results (use train_accuracy since test_accuracy is often NULL)
    cursor.execute("""
        SELECT 
            model_name,
            train_accuracy,
            test_accuracy,
            precision_score,
            recall_score,
            f1_score,
            ts_iso
        FROM ml_model_results
        WHERE archived = 0
        ORDER BY ts_iso DESC
        LIMIT 100
    """)
    
    models = []
    for row in cursor.fetchall():
        # Use whichever accuracy is available
        accuracy = row['test_accuracy'] if row['test_accuracy'] is not None else row['train_accuracy']
        
        models.append({
            "model_name": row['model_name'],
            "accuracy": round(accuracy * 100, 2) if accuracy else 0,
            "train_accuracy": round(row['train_accuracy'] * 100, 2) if row['train_accuracy'] else 0,
            "test_accuracy": round(row['test_accuracy'] * 100, 2) if row['test_accuracy'] else 0,
            "precision": round(row['precision_score'] * 100, 2) if row['precision_score'] else 0,
            "recall": round(row['recall_score'] * 100, 2) if row['recall_score'] else 0,
            "f1_score": round(row['f1_score'], 3) if row['f1_score'] else 0,
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
@safe_query
def api_reports(conn):
    """Get latest hourly/daily reports."""
    cursor = conn.cursor()
    
    # Get the latest report from filesystem
    latest_report_file = None
    if REPORTS_DIR.exists():
        report_files = sorted(REPORTS_DIR.glob("*.json"), reverse=True)
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
        "timestamp": datetime.utcnow().isoformat() + "Z"
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

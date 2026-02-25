#!/usr/bin/env python3
"""
Lightweight Blofin Dashboard Server - Optimized for performance
Only queries needed data, with aggressive caching and limits
"""

import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, send_file

app = Flask(__name__)

# Configuration
DATA_DIR = Path("/home/rob/.openclaw/workspace/blofin-stack/data")
DB_PATH = DATA_DIR / "blofin_monitor.db"
DASHBOARD_HTML = Path(__file__).parent / "blofin-dashboard.html"

# Simple response cache
_cache = {}
_cache_time = {}

def cached(func, ttl=15):
    """Cache responses for N seconds"""
    def wrapper(*args, **kwargs):
        key = func.__name__
        now = time.time()
        if key in _cache and (now - _cache_time.get(key, 0)) < ttl:
            return _cache[key]
        result = func(*args, **kwargs)
        _cache[key] = result
        _cache_time[key] = now
        return result
    return wrapper

@app.route('/')
def index():
    """Redirect to dashboard"""
    return send_file(DASHBOARD_HTML)

@app.route('/api/status')
def api_status():
    """Get current pipeline status - LIGHTWEIGHT"""
    return cached(lambda: _get_status_cached(), ttl=10)()

def _get_status_cached():
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get last 5 heartbeats only
        cursor.execute("""
            SELECT DISTINCT service, ts_iso 
            FROM service_heartbeats 
            ORDER BY ts_ms DESC 
            LIMIT 5
        """)
        services = [{"name": r['service'], "status": "running"} for r in cursor.fetchall()]
        
        conn.close()
        return jsonify({"status": "running", "services": services, "timestamp": datetime.utcnow().isoformat() + "Z"})
    except Exception as e:
        return jsonify({"error": str(e), "status": "error"}), 500

@app.route('/api/strategies')
def api_strategies():
    """Get top strategies - LIGHTWEIGHT"""
    return cached(lambda: _get_strategies_cached(), ttl=20)()

def _get_strategies_cached():
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Only get top 10 recent strategies
        cursor.execute("""
            SELECT strategy, sharpe_ratio, total_pnl_pct, win_rate, score
            FROM strategy_scores
            WHERE ts_iso > datetime('now', '-6 hours')
            ORDER BY score DESC LIMIT 10
        """)
        
        strategies = []
        for row in cursor.fetchall():
            strategies.append({
                "strategy": row['strategy'],
                "sharpe": row['sharpe_ratio'],
                "pnl_pct": row['total_pnl_pct'],
                "win_rate": row['win_rate'],
                "score": row['score']
            })
        
        conn.close()
        return jsonify({"strategies": strategies, "count": len(strategies)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/live-data')
def api_live_data():
    """Get real-time data flow - LIGHTWEIGHT"""
    return cached(lambda: _get_live_data_cached(), ttl=5)()

def _get_live_data_cached():
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Count recent ticks (only last row to avoid COUNT scan)
        cursor.execute("SELECT COUNT(*) as cnt FROM ticks WHERE ts_iso > datetime('now', '-10 seconds') LIMIT 1000")
        ticks = cursor.fetchone()['cnt']
        
        conn.close()
        return jsonify({"ticks_10s": ticks, "flowing": ticks > 0})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health():
    """Health check"""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=2)
        conn.execute("SELECT 1")
        conn.close()
        return jsonify({"status": "healthy"})
    except:
        return jsonify({"status": "unhealthy"}), 503

if __name__ == '__main__':
    print("🚀 Lightweight Blofin Dashboard on http://localhost:8888")
    app.run(host='127.0.0.1', port=8888, debug=False, threaded=True)

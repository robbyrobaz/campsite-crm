#!/usr/bin/env python3
import json
import os
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from db import connect, init_db

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
DB_PATH = os.getenv('BLOFIN_DB_PATH', str(ROOT / 'data' / 'blofin_monitor.db'))
HOST = os.getenv('API_HOST', '127.0.0.1')
PORT = int(os.getenv('API_PORT', '8780'))
SYMBOLS = [s.strip() for s in os.getenv('BLOFIN_SYMBOLS', '').split(',') if s.strip()]

con = connect(DB_PATH)
init_db(con)


def _in_clause(symbols):
    if not symbols:
        return '', []
    ph = ','.join('?' for _ in symbols)
    return f' WHERE symbol IN ({ph}) ', list(symbols)


def _grade_score(score: float) -> str:
    if score >= 85:
        return 'A'
    if score >= 70:
        return 'B'
    if score >= 55:
        return 'C'
    if score >= 40:
        return 'D'
    return 'F'


def fetch_summary():
    wh, args = _in_clause(SYMBOLS)
    sigs = [dict(r) for r in con.execute(f'SELECT ts_iso,symbol,signal,strategy,confidence,price,details_json FROM signals {wh} ORDER BY ts_ms DESC LIMIT 3000', args)]
    confirmed = [dict(r) for r in con.execute(f'SELECT ts_iso,symbol,signal,score,rationale FROM confirmed_signals {wh} ORDER BY ts_ms DESC LIMIT 300', args)]
    paper = [dict(r) for r in con.execute(f'SELECT opened_ts_iso,closed_ts_iso,symbol,side,entry_price,exit_price,status,pnl_pct,reason FROM paper_trades {wh} ORDER BY id DESC LIMIT 300', args)]
    by_sig = Counter(s['signal'] for s in sigs)
    by_strat = Counter(s['strategy'] for s in sigs)
    by_symbol_sig = Counter(s['symbol'] for s in sigs)
    latest_by_symbol = [dict(r) for r in con.execute(f'SELECT symbol, MAX(ts_iso) as last_seen, COUNT(*) as ticks FROM ticks {wh} GROUP BY symbol ORDER BY symbol', args)]

    now_ms = int(time.time() * 1000)
    tick_flow = dict(con.execute(
        f'''
        SELECT
            SUM(CASE WHEN ts_ms >= ? THEN 1 ELSE 0 END) AS ticks_10s,
            SUM(CASE WHEN ts_ms >= ? THEN 1 ELSE 0 END) AS ticks_60s,
            MAX(ts_ms) AS last_tick_ms
        FROM ticks
        {wh}
        ''',
        [now_ms - 10_000, now_ms - 60_000, *args],
    ).fetchone())
    last_tick_ms = tick_flow.get('last_tick_ms')
    seconds_since_last_tick = round(max(0.0, (now_ms - last_tick_ms) / 1000.0), 1) if last_tick_ms else None
    is_live = bool((tick_flow.get('ticks_10s') or 0) > 0 and seconds_since_last_tick is not None and seconds_since_last_tick <= 12)

    points_where, points_args = _in_clause(SYMBOLS)
    if points_where:
        points_where = points_where.replace('WHERE', 'WHERE ts_ms >= (CAST(strftime(\'%s\',\'now\') AS INTEGER) - 7*24*60*60) * 1000 AND', 1)
    else:
        points_where = " WHERE ts_ms >= (CAST(strftime('%s','now') AS INTEGER) - 7*24*60*60) * 1000 "

    points_by_symbol_7d = [dict(r) for r in con.execute(
        f'''
        SELECT symbol,
               COUNT(*) AS points_7d,
               COUNT(DISTINCT ((ts_ms / 60000) * 60000)) AS minute_buckets_7d
        FROM ticks
        {points_where}
        GROUP BY symbol
        ORDER BY symbol
        ''',
        points_args,
    )]

    expected_minutes_7d = 7 * 24 * 60
    points_by_symbol_map = {r['symbol']: r for r in points_by_symbol_7d}
    if SYMBOLS:
        points_by_symbol_7d = []
        for sym in SYMBOLS:
            row = points_by_symbol_map.get(sym, {'symbol': sym, 'points_7d': 0, 'minute_buckets_7d': 0})
            minute_buckets = int(row.get('minute_buckets_7d') or 0)
            coverage_pct = round((minute_buckets / expected_minutes_7d) * 100.0, 2)
            points_by_symbol_7d.append({
                'symbol': sym,
                'points_7d': int(row.get('points_7d') or 0),
                'minute_buckets_7d': minute_buckets,
                'expected_minutes_7d': expected_minutes_7d,
                'coverage_pct_7d': coverage_pct,
                'missing_minutes_7d': max(0, expected_minutes_7d - minute_buckets),
            })
    else:
        for row in points_by_symbol_7d:
            minute_buckets = int(row.get('minute_buckets_7d') or 0)
            row['expected_minutes_7d'] = expected_minutes_7d
            row['coverage_pct_7d'] = round((minute_buckets / expected_minutes_7d) * 100.0, 2)
            row['missing_minutes_7d'] = max(0, expected_minutes_7d - minute_buckets)

    points_by_symbol_7d.sort(key=lambda r: (-int(r.get('missing_minutes_7d') or 0), r.get('symbol', '')))
    total_missing_minutes_7d = int(sum(int(r.get('missing_minutes_7d') or 0) for r in points_by_symbol_7d))
    worst_symbol_7d = points_by_symbol_7d[0]['symbol'] if points_by_symbol_7d else None
    worst_coverage_pct_7d = float(min((r.get('coverage_pct_7d', 0.0) for r in points_by_symbol_7d), default=0.0))
    coverage_health = 'good' if worst_coverage_pct_7d >= 99.5 else ('warn' if worst_coverage_pct_7d >= 97.0 else 'critical')

    # Coverage since first data point (realistic metric)
    coverage_since_start = []
    for sym in SYMBOLS:
        earliest_row = con.execute('SELECT MIN(ts_ms) FROM ticks WHERE symbol=?', (sym,)).fetchone()
        if not earliest_row or not earliest_row[0]:
            continue
        earliest_ms = int(earliest_row[0])
        actual_buckets = int(con.execute(
            'SELECT COUNT(DISTINCT ((ts_ms / 60000) * 60000)) FROM ticks WHERE symbol=? AND ts_ms >= ?',
            (sym, earliest_ms)
        ).fetchone()[0])
        expected_buckets = int((now_ms - earliest_ms) / 60000)
        coverage_pct = round((actual_buckets / expected_buckets) * 100.0, 2) if expected_buckets > 0 else 0.0
        hours_active = round((now_ms - earliest_ms) / 3600000.0, 1)
        coverage_since_start.append({
            'symbol': sym,
            'hours_active': hours_active,
            'coverage_pct': coverage_pct,
            'actual_minutes': actual_buckets,
            'expected_minutes': expected_buckets,
            'missing_minutes': max(0, expected_buckets - actual_buckets),
        })
    coverage_since_start.sort(key=lambda r: r['coverage_pct'])
    worst_coverage_since_start = coverage_since_start[0]['coverage_pct'] if coverage_since_start else 100.0
    real_health = 'good' if worst_coverage_since_start >= 99.5 else ('warn' if worst_coverage_since_start >= 97.0 else 'critical')

    gaps = [dict(r) for r in con.execute(f'SELECT ts_iso,symbol,gaps_found,rows_inserted,note FROM gap_fill_runs {wh} ORDER BY id DESC LIMIT 100', args)]
    closed = [p for p in paper if p['status'] == 'CLOSED' and p['pnl_pct'] is not None]
    win_rate = (sum(1 for p in closed if p['pnl_pct'] > 0) / len(closed) * 100.0) if closed else 0.0

    perf_where, perf_args = _in_clause(SYMBOLS)
    perf_rows = [dict(r) for r in con.execute(
        f'''
        SELECT
            s.strategy AS strategy,
            cs.signal AS pattern,
            COUNT(*) AS closed_count,
            SUM(CASE WHEN pt.pnl_pct > 0 THEN 1 ELSE 0 END) AS wins,
            AVG(pt.pnl_pct) AS avg_pnl_pct,
            SUM(pt.pnl_pct) AS total_pnl_pct
        FROM paper_trades pt
        JOIN confirmed_signals cs ON cs.id = pt.confirmed_signal_id
        JOIN signals s ON s.id = cs.signal_id
        {perf_where.replace('symbol', 'pt.symbol')}
          {'AND' if perf_where else 'WHERE'} pt.status='CLOSED' AND pt.pnl_pct IS NOT NULL
        GROUP BY s.strategy, cs.signal
        ORDER BY total_pnl_pct DESC, avg_pnl_pct DESC
        ''',
        perf_args,
    )]

    strategy_pattern_scores = []
    for row in perf_rows:
        closed_count = int(row['closed_count'] or 0)
        wins = int(row['wins'] or 0)
        win_rate_pct = (wins / closed_count * 100.0) if closed_count else 0.0
        avg_pnl_pct = float(row['avg_pnl_pct'] or 0.0)
        total_pnl_pct = float(row['total_pnl_pct'] or 0.0)
        if closed_count < 3:
            score = None
            grade = 'N/A'
        else:
            pnl_component = max(0.0, min(100.0, ((avg_pnl_pct + 2.0) / 4.0) * 100.0))
            score = round((win_rate_pct * 0.6) + (pnl_component * 0.4), 2)
            grade = _grade_score(score)
        strategy_pattern_scores.append({
            'strategy': row['strategy'],
            'pattern': row['pattern'],
            'closed_count': closed_count,
            'wins': wins,
            'win_rate_pct': round(win_rate_pct, 2),
            'avg_pnl_pct': round(avg_pnl_pct, 4),
            'total_pnl_pct': round(total_pnl_pct, 4),
            'score': score,
            'grade': grade,
        })

    return {
        'symbols_configured': SYMBOLS,
        'signals_total_window': len(sigs),
        'signals_by_type': dict(by_sig),
        'signals_by_strategy': dict(by_strat),
        'signals_by_symbol': dict(by_symbol_sig.most_common(25)),
        'latest_by_symbol': latest_by_symbol,
        'live_status': {
            'is_live': is_live,
            'ticks_10s': int(tick_flow.get('ticks_10s') or 0),
            'ticks_60s': int(tick_flow.get('ticks_60s') or 0),
            'last_tick_ms': last_tick_ms,
            'seconds_since_last_tick': seconds_since_last_tick,
        },
        'points_by_symbol_7d': points_by_symbol_7d,
        'coverage_overview_7d': {
            'total_missing_minutes': total_missing_minutes_7d,
            'worst_symbol': worst_symbol_7d,
            'worst_coverage_pct': round(worst_coverage_pct_7d, 2),
            'health': coverage_health,
        },
        'coverage_since_start': coverage_since_start,
        'coverage_health_real': {
            'worst_coverage_pct': round(worst_coverage_since_start, 2),
            'health': real_health,
        },
        'recent_signals': sigs[:120],
        'confirmed_signals': confirmed[:120],
        'paper_trades': paper[:120],
        'paper_stats': {
            'closed_count': len(closed),
            'open_count': sum(1 for p in paper if p['status'] == 'OPEN'),
            'win_rate_pct': round(win_rate, 2),
            'avg_pnl_pct': round(sum(p['pnl_pct'] for p in closed) / len(closed), 4) if closed else 0.0,
        },
        'strategy_pattern_scores': strategy_pattern_scores[:120],
        'gap_fill_runs': gaps,
    }


def timeseries(symbol: str, limit: int = 300):
    rows = con.execute('SELECT ts_iso, price, source FROM ticks WHERE symbol=? ORDER BY ts_ms DESC LIMIT ?', (symbol, limit)).fetchall()
    out = [dict(r) for r in rows]
    out.reverse()
    return out


class H(BaseHTTPRequestHandler):
    def sendb(self, b: bytes, code=200, ctype='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = urlparse(self.path)
        q = parse_qs(p.query)

        if p.path == '/healthz':
            return self.sendb(b'ok', ctype='text/plain')
        if p.path == '/api/summary':
            return self.sendb(json.dumps(fetch_summary(), default=str).encode())
        if p.path == '/api/timeseries':
            symbol = q.get('symbol', [SYMBOLS[0] if SYMBOLS else 'PEPE-USDT'])[0]
            limit = int(q.get('limit', ['300'])[0])
            return self.sendb(json.dumps(timeseries(symbol, max(30, min(limit, 2000))), default=str).encode())
        if p.path == '/api/gap-fills':
            rows = [dict(r) for r in con.execute('SELECT * FROM gap_fill_runs ORDER BY id DESC LIMIT 200')]
            return self.sendb(json.dumps(rows, default=str).encode())

        if p.path == '/':
            s = fetch_summary()
            
            # Helper for PnL coloring
            def pnl_color(val):
                if val is None or val == '':
                    return '#9fb0e6'
                try:
                    v = float(val)
                    return '#10b981' if v > 0 else ('#ef4444' if v < 0 else '#9fb0e6')
                except:
                    return '#9fb0e6'
            
            # Helper for grade color
            def grade_color(grade):
                if grade == 'A': return '#10b981'
                if grade == 'B': return '#3b82f6'
                if grade == 'C': return '#f59e0b'
                if grade == 'D': return '#f97316'
                if grade == 'F': return '#ef4444'
                return '#6b7280'
            
            # Helper for signal color
            def signal_color(sig):
                if 'BUY' in sig.upper():
                    return '#10b981'
                elif 'SELL' in sig.upper():
                    return '#ef4444'
                return '#3b82f6'
            
            html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Blofin 24/7 Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<script src='https://cdn.jsdelivr.net/npm/chart.js'></script>
<style>
* {{box-sizing: border-box;}}
body {{
  margin:0;
  background: linear-gradient(135deg, #0a0e1a 0%, #0f1629 100%);
  color:#e7ecff;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, Arial, sans-serif;
  animation: fadeIn 0.6s ease-in;
}}
@keyframes fadeIn {{
  from {{ opacity: 0; }}
  to {{ opacity: 1; }}
}}
@keyframes pulse {{
  0%, 100% {{ opacity: 1; }}
  50% {{ opacity: 0.6; }}
}}
.wrap {{
  max-width:1400px;
  margin:0 auto;
  padding:24px;
}}
h1 {{
  font-size: 32px;
  font-weight: 700;
  background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: 0 0 24px 0;
}}
.section-title {{
  font-size: 14px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #94a3b8;
  margin: 32px 0 16px 0;
  padding-bottom: 8px;
  border-bottom: 2px solid #1e293b;
}}
.grid {{
  display:grid;
  grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));
  gap:16px;
  margin-bottom: 20px;
}}
.card {{
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 16px;
  padding: 20px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3), 0 0 20px rgba(99, 102, 241, 0.05);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  position: relative;
  overflow: hidden;
}}
.card::before {{
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6, #ec4899);
  opacity: 0.6;
}}
.card:hover {{
  transform: translateY(-2px);
  box-shadow: 0 8px 12px rgba(0, 0, 0, 0.4), 0 0 30px rgba(99, 102, 241, 0.15);
}}
.small {{
  font-size:11px;
  color:#94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 600;
  margin-bottom: 8px;
}}
.stat-value {{
  font-size:28px;
  font-weight:700;
  line-height: 1.2;
}}
.live-indicator {{
  animation: pulse 2s ease-in-out infinite;
}}
table {{
  width:100%;
  border-collapse:collapse;
  font-size:13px;
}}
thead {{
  background: rgba(30, 41, 59, 0.5);
}}
th {{
  padding:12px;
  text-align:left;
  font-weight:600;
  color:#cbd5e1;
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: 0.5px;
  border-bottom: 2px solid #334155;
}}
td {{
  padding:12px;
  border-bottom:1px solid rgba(51, 65, 85, 0.3);
}}
tbody tr {{
  transition: background-color 0.15s ease;
}}
tbody tr:nth-child(even) {{
  background: rgba(30, 41, 59, 0.2);
}}
tbody tr:hover {{
  background: rgba(59, 130, 246, 0.1);
}}
select {{
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  color:#e7ecff;
  border:1px solid rgba(148, 163, 184, 0.3);
  padding:10px 16px;
  border-radius:10px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}}
select:hover {{
  border-color: #60a5fa;
  box-shadow: 0 0 10px rgba(96, 165, 250, 0.3);
}}
.badge {{
  display:inline-block;
  padding:6px 12px;
  border-radius:20px;
  background: linear-gradient(135deg, #1e40af 0%, #3730a3 100%);
  margin:4px 6px 4px 0;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid rgba(96, 165, 250, 0.3);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.1);
  transition: transform 0.15s ease;
}}
.badge:hover {{
  transform: scale(1.05);
}}
.chart-container {{
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3), 0 0 30px rgba(139, 92, 246, 0.1);
  margin: 24px 0;
}}
.chart-header {{
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin-bottom: 20px;
}}
.chart-header h3 {{
  margin:0;
  font-size: 20px;
  font-weight: 600;
  color: #e2e8f0;
}}
.table-container {{
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
  margin: 16px 0;
  overflow: hidden;
}}
.table-container h3 {{
  margin:0 0 16px 0;
  font-size: 18px;
  font-weight: 600;
  color: #e2e8f0;
}}
.table-wrapper {{
  overflow-x: auto;
}}
.toggle-btn {{
  margin-top: 16px;
  padding: 10px 20px;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: white;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.2s ease;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}}
.toggle-btn:hover {{
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(59, 130, 246, 0.4);
}}
.pill {{
  display: inline-block;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}}
.pill-buy {{
  background: rgba(16, 185, 129, 0.2);
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.4);
}}
.pill-sell {{
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.4);
}}
.grade-badge {{
  display: inline-block;
  padding: 4px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
  text-align: center;
  min-width: 32px;
}}
.footer {{
  margin-top: 48px;
  padding: 24px 0;
  text-align: center;
  color: #64748b;
  font-size: 13px;
  border-top: 1px solid rgba(51, 65, 85, 0.3);
}}
.footer strong {{
  color: #94a3b8;
  font-weight: 600;
}}
.win-rate-bar {{
  display: inline-block;
  width: 60px;
  height: 8px;
  background: rgba(100, 116, 139, 0.3);
  border-radius: 4px;
  overflow: hidden;
  vertical-align: middle;
  margin-left: 8px;
}}
.win-rate-fill {{
  height: 100%;
  background: linear-gradient(90deg, #10b981, #059669);
  transition: width 0.3s ease;
}}
@media (max-width: 768px) {{
  .grid {{
    grid-template-columns: repeat(2, 1fr);
  }}
  h1 {{
    font-size: 24px;
  }}
  .wrap {{
    padding: 16px;
  }}
}}
</style>
</head>
<body>
<div class='wrap'>
<h1>Blofin 24/7 Pattern Dashboard</h1>

<div class='grid'>
<div class='card'>
  <div class='small'>Live Feed</div>
  <div id='live-pill' class='stat-value {"live-indicator" if s['live_status']['is_live'] else ""}' style='color:{"#10b981" if s['live_status']['is_live'] else "#ef4444"}'>{'LIVE' if s['live_status']['is_live'] else 'STALE'}</div>
  <div class='small' id='live-detail'>{s['live_status']['ticks_10s']} ticks / 10s · {s['live_status']['seconds_since_last_tick'] if s['live_status']['seconds_since_last_tick'] is not None else 'n/a'}s ago</div>
</div>
<div class='card'>
  <div class='small'>Configured Tokens</div>
  <div id='configured-count' class='stat-value'>{len(s['symbols_configured'])}</div>
</div>
<div class='card'>
  <div class='small'>Signals</div>
  <div id='signals-count' class='stat-value'>{s['signals_total_window']}</div>
</div>
<div class='card'>
  <div class='small'>Confirmed</div>
  <div id='confirmed-count' class='stat-value'>{len(s['confirmed_signals'])}</div>
</div>
<div class='card'>
  <div class='small'>Paper Win Rate</div>
  <div id='paper-win-rate' class='stat-value' style='color:#{"10b981" if s["paper_stats"]["win_rate_pct"] >= 50 else "f59e0b"}'>{s['paper_stats']['win_rate_pct']}%</div>
  <div class='win-rate-bar'><div class='win-rate-fill' style='width:{min(100, s["paper_stats"]["win_rate_pct"])}%'></div></div>
</div>
<div class='card'>
  <div class='small'>Data Quality</div>
  <div id='coverage-health' class='stat-value' style='color:{"#10b981" if s['coverage_health_real']['health']=='good' else ("#f59e0b" if s['coverage_health_real']['health']=='warn' else "#ef4444")}'>{{str(s['coverage_health_real']['health']).upper()}}</div>
  <div class='small' id='coverage-detail'>worst {s['coverage_health_real']['worst_coverage_pct']}% since start</div>
</div>
</div>

<div style='margin: 20px 0;'>
{''.join([f"<span class='badge'>{x}</span>" for x in s['symbols_configured']])}
</div>

<div class='section-title'>🏆 Strategy Performance Scorecard</div>
<div class='table-container'>
<h3>Top performing strategies & patterns</h3>
<div class='table-wrapper'>
<table id='scorecard-table'><thead><tr><th>Strategy</th><th>Pattern</th><th>Closed</th><th>Win%</th><th>Avg PnL%</th><th>Total PnL%</th><th>Score</th><th>Grade</th></tr></thead>
<tbody>
{''.join([f"<tr class='{'hidden-row' if i >= 10 else ''}' data-table='scorecard'><td>{r['strategy']}</td><td><span class='pill pill-{"buy" if "BUY" in r["pattern"].upper() else "sell"}'>{r['pattern']}</span></td><td>{r['closed_count']}</td><td>{r['win_rate_pct']}%</td><td style='color:{pnl_color(r["avg_pnl_pct"])};font-weight:600'>{r['avg_pnl_pct']}</td><td style='color:{pnl_color(r["total_pnl_pct"])};font-weight:700'>{r['total_pnl_pct']}</td><td>{r['score'] if r['score'] is not None else 'N/A'}</td><td><span class='grade-badge' style='background:{grade_color(r["grade"])};color:white'>{r['grade']}</span></td></tr>" for i, r in enumerate(s['strategy_pattern_scores'])])}
</tbody>
</table>
</div>
<button class='toggle-btn' onclick='toggleTable("scorecard", {len(s["strategy_pattern_scores"])})' id='toggle-scorecard'>Show all ({len(s['strategy_pattern_scores'])})</button>
</div>

<div class='section-title'>📈 Live Price Chart</div>
<div class='chart-container'>
<div class='chart-header'>
<h3>Token Price Movement</h3>
<div><select id='sym'>{''.join([f"<option>{x}</option>" for x in s['symbols_configured']])}</select></div>
</div>
<canvas id='chart' height='80'></canvas>
</div>

<div class='section-title'>✅ Recent Confirmed Signals</div>
<div class='table-container'>
<h3>High-confidence pattern detections</h3>
<div class='table-wrapper'>
<table id='confirmed-table'><thead><tr><th>Time</th><th>Symbol</th><th>Signal</th><th>Score</th><th>Rationale</th></tr></thead>
<tbody>
{''.join([f"<tr class='{'hidden-row' if i >= 10 else ''}' data-table='confirmed'><td>{r['ts_iso'][11:19]}</td><td><strong>{r['symbol']}</strong></td><td><span class='pill pill-{"buy" if "BUY" in r["signal"].upper() else "sell"}'>{r['signal']}</span></td><td style='font-weight:600;color:#60a5fa'>{r['score']}</td><td style='font-size:12px;color:#94a3b8'>{r['rationale'][:100]}</td></tr>" for i, r in enumerate(s['confirmed_signals'])])}
</tbody>
</table>
</div>
<button class='toggle-btn' onclick='toggleTable("confirmed", {len(s["confirmed_signals"])})' id='toggle-confirmed'>Show all ({len(s['confirmed_signals'])})</button>
</div>

<div class='section-title'>💼 Paper Trades</div>
<div class='table-container'>
<h3>Simulated trade executions</h3>
<div class='table-wrapper'>
<table id='trades-table'><thead><tr><th>Symbol</th><th>Side</th><th>Status</th><th>Entry</th><th>Exit</th><th>PNL%</th><th>Reason</th></tr></thead>
<tbody>
{''.join([f"<tr class='{'hidden-row' if i >= 10 else ''}' data-table='trades'><td><strong>{r['symbol']}</strong></td><td><span class='pill pill-{"buy" if r["side"]=="LONG" else "sell"}'>{r['side']}</span></td><td>{r['status']}</td><td style='color:#94a3b8'>{r['entry_price']}</td><td style='color:#94a3b8'>{r['exit_price'] or '—'}</td><td style='color:{pnl_color(r["pnl_pct"])};font-weight:700'>{r['pnl_pct'] if r['pnl_pct'] else '—'}</td><td style='font-size:11px;color:#64748b'>{(r['reason'] or '')[:80]}</td></tr>" for i, r in enumerate(s['paper_trades'])])}
</tbody>
</table>
</div>
<button class='toggle-btn' onclick='toggleTable("trades", {len(s["paper_trades"])})' id='toggle-trades'>Show all ({len(s['paper_trades'])})</button>
</div>

<div class='section-title'>📊 Data Quality Per Symbol</div>
<div class='table-container'>
<h3>Coverage metrics since first data point</h3>
<div class='table-wrapper'>
<table id='quality-table'><thead><tr><th>Symbol</th><th>Hours Active</th><th>Coverage</th><th>Minutes</th><th>Missing</th></tr></thead>
<tbody>
{''.join([f"<tr class='{'hidden-row' if i >= 10 else ''}' data-table='quality'><td><strong>{r['symbol']}</strong></td><td>{r['hours_active']:.1f}h</td><td style='color:{("#10b981" if r["coverage_pct"] >= 99.5 else ("#f59e0b" if r["coverage_pct"] >= 97 else "#ef4444"))};font-weight:600'>{r['coverage_pct']:.2f}%</td><td style='color:#94a3b8;font-size:12px'>{r['actual_minutes']:,} / {r['expected_minutes']:,}</td><td style='color:#ef4444;font-weight:600'>{r['missing_minutes']:,}</td></tr>" for i, r in enumerate(s['coverage_since_start'])])}
</tbody>
</table>
</div>
<button class='toggle-btn' onclick='toggleTable("quality", {len(s["coverage_since_start"])})' id='toggle-quality'>Show all ({len(s['coverage_since_start'])})</button>
</div>

<div class='section-title'>🔧 Gap Fill Operations</div>
<div class='table-container'>
<h3>Historical data backfill runs</h3>
<div class='table-wrapper'>
<table id='gaps-table'><thead><tr><th>Run Time</th><th>Symbol</th><th>Gaps Found</th><th>Rows Inserted</th><th>Note</th></tr></thead>
<tbody>
{''.join([f"<tr class='{'hidden-row' if i >= 10 else ''}' data-table='gaps'><td>{g['ts_iso'][11:19]}</td><td><strong>{g['symbol']}</strong></td><td style='color:#f59e0b;font-weight:600'>{g['gaps_found']}</td><td style='color:#10b981;font-weight:600'>{g['rows_inserted']}</td><td style='font-size:11px;color:#64748b'>{g['note'][:80]}</td></tr>" for i, g in enumerate(s['gap_fill_runs'])])}
</tbody>
</table>
</div>
<button class='toggle-btn' onclick='toggleTable("gaps", {len(s["gap_fill_runs"])})' id='toggle-gaps'>Show all ({len(s['gap_fill_runs'])})</button>
</div>

<div class='footer'>
<strong>Blofin 24/7 Monitor</strong> · Last updated: <span id='timestamp'>{time.strftime('%Y-%m-%d %H:%M:%S')}</span>
</div>

</div>

<script>
let ch;

function toggleTable(name, total) {{{{
  const rows = document.querySelectorAll(`tr.hidden-row[data-table="${{name}}"]`);
  const btn = document.getElementById(`toggle-${{name}}`);
  const isHidden = rows[0]?.classList.contains('hidden-row');
  
  rows.forEach(row => {{{{
    if (isHidden) {{{{
      row.style.display = '';
      row.classList.remove('hidden-row');
    }}}} else {{{{
      row.style.display = 'none';
      row.classList.add('hidden-row');
    }}}}
  }}}});
  
  btn.textContent = isHidden ? 'Show less' : `Show all (${{total}})`;
}}}}

document.querySelectorAll('.hidden-row').forEach(row => {{{{
  row.style.display = 'none';
}}}});

async function loadSym(sym) {{{{
  const r = await fetch('/api/timeseries?symbol=' + encodeURIComponent(sym) + '&limit=300');
  const d = await r.json();
  const labels = d.map(x => x.ts_iso.slice(11,19));
  const vals = d.map(x => x.price);
  if(ch) ch.destroy();
  ch = new Chart(document.getElementById('chart'), {{{{
    type: 'line',
    data: {{{{
      labels,
      datasets: [{{{{
        label: sym,
        data: vals,
        borderColor: '#8b5cf6',
        backgroundColor: 'rgba(139, 92, 246, 0.1)',
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.1,
        fill: true
      }}}}]
    }}}},
    options: {{{{
      responsive: true,
      maintainAspectRatio: true,
      plugins: {{{{
        legend: {{{{
          display: true,
          labels: {{{{
            color: '#e2e8f0',
            font: {{{{
              size: 13,
              weight: 600
            }}}}
          }}}}
        }}}}
      }}}},
      scales: {{{{
        x: {{{{
          ticks: {{{{ color: '#64748b', maxRotation: 0 }}}},
          grid: {{{{ color: 'rgba(51, 65, 85, 0.3)' }}}}
        }}}},
        y: {{{{
          ticks: {{{{ color: '#64748b' }}}},
          grid: {{{{ color: 'rgba(51, 65, 85, 0.3)' }}}}
        }}}}
      }}}}
    }}}}
  }});
}}}}

function renderLive(status) {{{{
  const live = !!status?.is_live;
  const pill = document.getElementById('live-pill');
  const detail = document.getElementById('live-detail');
  if (!pill || !detail) return;
  pill.textContent = live ? 'LIVE' : 'STALE';
  pill.style.color = live ? '#10b981' : '#ef4444';
  if (live) {{{{
    pill.classList.add('live-indicator');
  }}}} else {{{{
    pill.classList.remove('live-indicator');
  }}}}
  const age = status?.seconds_since_last_tick;
  detail.textContent = `${{status?.ticks_10s ?? 0}} ticks / 10s · ${{age ?? 'n/a'}}s ago`;
}}}}

async function refreshSummary() {{{{
  try {{{{
    const r = await fetch('/api/summary');
    const s = await r.json();
    renderLive(s.live_status || {{}});
    
    const signals = document.getElementById('signals-count');
    const confirmed = document.getElementById('confirmed-count');
    const win = document.getElementById('paper-win-rate');
    const coverage = document.getElementById('coverage-health');
    const coverageDetail = document.getElementById('coverage-detail');
    const timestamp = document.getElementById('timestamp');
    
    if (signals) signals.textContent = s.signals_total_window ?? 0;
    if (confirmed) confirmed.textContent = (s.confirmed_signals || []).length;
    
    const winRate = s.paper_stats?.win_rate_pct ?? 0;
    if (win) {{{{
      win.textContent = `${{winRate}}%`;
      win.style.color = winRate >= 50 ? '#10b981' : '#f59e0b';
    }}}}
    
    const ov = s.coverage_health_real || {{}};
    if (coverage) {{{{
      const health = String(ov.health || 'critical').toLowerCase();
      coverage.textContent = health.toUpperCase();
      coverage.style.color = health === 'good' ? '#10b981' : (health === 'warn' ? '#f59e0b' : '#ef4444');
    }}}}
    if (coverageDetail) {{{{
      coverageDetail.textContent = `worst ${{ov.worst_coverage_pct ?? 0}}% since start`;
    }}}}
    if (timestamp) {{{{
      const now = new Date();
      timestamp.textContent = now.toISOString().slice(0, 19).replace('T', ' ');
    }}}}
  }}}} catch (err) {{{{
    console.error('Refresh failed:', err);
    renderLive({{{{is_live:false, ticks_10s:0, seconds_since_last_tick:'n/a'}}}});
  }}}}
}}}}

const sel = document.getElementById('sym');
sel.addEventListener('change', () => loadSym(sel.value));
if (sel.value) loadSym(sel.value);

refreshSummary();
setInterval(refreshSummary, 5000);
setInterval(() => {{{{ if (sel.value) loadSym(sel.value); }}}}, 15000);
</script>
</body>
</html>"""
            return self.sendb(html.encode(), ctype='text/html; charset=utf-8')

        return self.sendb(json.dumps({'error': 'not found'}).encode(), code=404)


if __name__ == '__main__':
    HTTPServer((HOST, PORT), H).serve_forever()

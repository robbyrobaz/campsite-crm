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
            html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Blofin 24/7 Dashboard</title>
<script src='https://cdn.jsdelivr.net/npm/chart.js'></script>
<style>
body{{margin:0;background:#0b1020;color:#e7ecff;font-family:Inter,Arial,sans-serif}}
.wrap{{max-width:1200px;margin:0 auto;padding:20px}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}
.card{{background:#121a31;border:1px solid #23325f;border-radius:12px;padding:12px}}
.small{{font-size:12px;color:#9fb0e6}}
table{{width:100%;border-collapse:collapse}} th,td{{padding:8px;border-bottom:1px solid #22335f;font-size:12px;text-align:left}}
select{{background:#0e1730;color:#e7ecff;border:1px solid #2b427a;padding:6px;border-radius:8px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:8px;background:#203766;margin-right:6px}}
</style></head>
<body><div class='wrap'>
<h1>Blofin 24/7 Pattern Dashboard</h1>
<div class='grid' style='grid-template-columns:repeat(6,minmax(0,1fr))'>
<div class='card'>
  <div class='small'>Live Feed</div>
  <div id='live-pill' style='font-size:22px;font-weight:700;color:{'#2fe38a' if s['live_status']['is_live'] else '#ff6b6b'}'>{'LIVE' if s['live_status']['is_live'] else 'STALE'}</div>
  <div class='small' id='live-detail'>{s['live_status']['ticks_10s']} ticks / 10s · last {s['live_status']['seconds_since_last_tick'] if s['live_status']['seconds_since_last_tick'] is not None else 'n/a'}s</div>
</div>
<div class='card'><div class='small'>Configured Tokens</div><div id='configured-count' style='font-size:26px'>{len(s['symbols_configured'])}</div></div>
<div class='card'><div class='small'>Signals</div><div id='signals-count' style='font-size:26px'>{s['signals_total_window']}</div></div>
<div class='card'><div class='small'>Confirmed</div><div id='confirmed-count' style='font-size:26px'>{len(s['confirmed_signals'])}</div></div>
<div class='card'><div class='small'>Paper Win Rate</div><div id='paper-win-rate' style='font-size:26px'>{s['paper_stats']['win_rate_pct']}%</div></div>
<div class='card'>
  <div class='small'>Data Quality</div>
  <div id='coverage-health' style='font-size:22px;font-weight:700;color:{'#2fe38a' if s['coverage_health_real']['health']=='good' else ('#ffd166' if s['coverage_health_real']['health']=='warn' else '#ff6b6b')}'>{str(s['coverage_health_real']['health']).upper()}</div>
  <div class='small' id='coverage-detail'>worst {s['coverage_health_real']['worst_coverage_pct']}% since start</div>
</div>
</div>
<p>{''.join([f"<span class='badge'>{x}</span>" for x in s['symbols_configured']])}</p>

<div class='card' style='margin-top:12px'>
<div style='display:flex;justify-content:space-between;align-items:center'>
<h3 style='margin:0'>Token chart</h3>
<div><select id='sym'>{''.join([f"<option>{x}</option>" for x in s['symbols_configured']])}</select></div>
</div>
<canvas id='chart' height='100'></canvas>
</div>

<div class='card' style='margin-top:12px'>
<h3 style='margin-top:0'>Recent confirmed signals</h3>
<table><thead><tr><th>Time</th><th>Symbol</th><th>Signal</th><th>Score</th><th>Why</th></tr></thead><tbody>
{''.join([f"<tr><td>{r['ts_iso']}</td><td>{r['symbol']}</td><td>{r['signal']}</td><td>{r['score']}</td><td>{r['rationale']}</td></tr>" for r in s['confirmed_signals'][:60]])}
</tbody></table>
</div>

<div class='card' style='margin-top:12px'>
<h3 style='margin-top:0'>Paper trades</h3>
<table><thead><tr><th>Symbol</th><th>Side</th><th>Status</th><th>Entry</th><th>Exit</th><th>PNL%</th><th>Reason</th></tr></thead><tbody>
{''.join([f"<tr><td>{r['symbol']}</td><td>{r['side']}</td><td>{r['status']}</td><td>{r['entry_price']}</td><td>{r['exit_price'] or ''}</td><td>{r['pnl_pct'] or ''}</td><td>{r['reason'] or ''}</td></tr>" for r in s['paper_trades'][:80]])}
</tbody></table>
</div>

<div class='card' style='margin-top:12px'>
<h3 style='margin-top:0'>Data quality per symbol (since first data)</h3>
<table><thead><tr><th>Symbol</th><th>Hours Active</th><th>Coverage</th><th>Minutes</th><th>Missing</th></tr></thead><tbody>
{''.join([f"<tr><td>{r['symbol']}</td><td>{r['hours_active']:.1f}h</td><td>{r['coverage_pct']:.1f}%</td><td>{r['actual_minutes']}/{r['expected_minutes']}</td><td>{r['missing_minutes']}</td></tr>" for r in s['coverage_since_start']])}
</tbody></table>
</div>

<div class='card' style='margin-top:12px'>
<h3 style='margin-top:0'>Strategy/pattern scorecard</h3>
<table><thead><tr><th>Strategy</th><th>Pattern</th><th>Closed</th><th>Win%</th><th>Avg PnL%</th><th>Total PnL%</th><th>Score</th><th>Grade</th></tr></thead><tbody>
{''.join([f"<tr><td>{r['strategy']}</td><td>{r['pattern']}</td><td>{r['closed_count']}</td><td>{r['win_rate_pct']}</td><td>{r['avg_pnl_pct']}</td><td>{r['total_pnl_pct']}</td><td>{r['score'] if r['score'] is not None else ''}</td><td>{r['grade']}</td></tr>" for r in s['strategy_pattern_scores'][:80]])}
</tbody></table>
</div>

<div class='card' style='margin-top:12px'>
<h3 style='margin-top:0'>Gap fills (historical backfill)</h3>
<table><thead><tr><th>Run time</th><th>Symbol</th><th>Gaps</th><th>Rows inserted</th><th>Note</th></tr></thead><tbody>
{''.join([f"<tr><td>{g['ts_iso']}</td><td>{g['symbol']}</td><td>{g['gaps_found']}</td><td>{g['rows_inserted']}</td><td>{g['note']}</td></tr>" for g in s['gap_fill_runs'][:60]])}
</tbody></table>
</div>
</div>
<script>
let ch;
async function loadSym(sym){{
  const r=await fetch('/api/timeseries?symbol='+encodeURIComponent(sym)+'&limit=300');
  const d=await r.json();
  const labels=d.map(x=>x.ts_iso.slice(11,19));
  const vals=d.map(x=>x.price);
  if(ch) ch.destroy();
  ch=new Chart(document.getElementById('chart'),{{type:'line',data:{{labels,datasets:[{{label:sym,data:vals,borderColor:'#6ea8fe',pointRadius:0}}]}},options:{{responsive:true}}}});
}}

function renderLive(status){{
  const live = !!status?.is_live;
  const pill = document.getElementById('live-pill');
  const detail = document.getElementById('live-detail');
  if (!pill || !detail) return;
  pill.textContent = live ? 'LIVE' : 'STALE';
  pill.style.color = live ? '#2fe38a' : '#ff6b6b';
  const age = status?.seconds_since_last_tick;
  detail.textContent = `${{status?.ticks_10s ?? 0}} ticks / 10s · last ${{age ?? 'n/a'}}s`;
}}

async function refreshSummary(){{
  try {{
    const r = await fetch('/api/summary');
    const s = await r.json();
    renderLive(s.live_status || {{}});
    const signals = document.getElementById('signals-count');
    const confirmed = document.getElementById('confirmed-count');
    const win = document.getElementById('paper-win-rate');
    const coverage = document.getElementById('coverage-health');
    const coverageDetail = document.getElementById('coverage-detail');
    if (signals) signals.textContent = s.signals_total_window ?? 0;
    if (confirmed) confirmed.textContent = (s.confirmed_signals || []).length;
    if (win) win.textContent = `${{s.paper_stats?.win_rate_pct ?? 0}}%`;
    const ov = s.coverage_health_real || {{}};
    if (coverage) {{
      const health = String(ov.health || 'critical').toLowerCase();
      coverage.textContent = health.toUpperCase();
      coverage.style.color = health === 'good' ? '#2fe38a' : (health === 'warn' ? '#ffd166' : '#ff6b6b');
    }}
    if (coverageDetail) {{
      coverageDetail.textContent = `worst ${{ov.worst_coverage_pct ?? 0}}% since start`;
    }}
  }} catch (err) {{
    renderLive({{is_live:false,ticks_10s:0,seconds_since_last_tick:'n/a'}});
  }}
}}

const sel=document.getElementById('sym');
sel.addEventListener('change',()=>loadSym(sel.value));
if(sel.value) loadSym(sel.value);
refreshSummary();
setInterval(refreshSummary, 5000);
setInterval(() => {{ if (sel.value) loadSym(sel.value); }}, 15000);
</script></body></html>"""
            return self.sendb(html.encode(), ctype='text/html; charset=utf-8')

        return self.sendb(json.dumps({'error': 'not found'}).encode(), code=404)


if __name__ == '__main__':
    HTTPServer((HOST, PORT), H).serve_forever()

#!/usr/bin/env python3
import json
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DB_PATH = Path('/home/rob/.openclaw/workspace/blofin-stack/data/blofin_monitor.db')
HOST = '127.0.0.1'
PORT = 8766


def q(sql, args=()):
    if not DB_PATH.exists():
        return []
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(sql, args).fetchall()
    con.close()
    return [dict(r) for r in rows]


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


def metrics():
    one_hour = int(datetime.now(timezone.utc).timestamp() * 1000) - 3600_000
    total_ticks = q('SELECT COUNT(*) c FROM ticks')
    total_signals = q('SELECT COUNT(*) c FROM signals')
    ticks_1h = q('SELECT COUNT(*) c FROM ticks WHERE ts_ms >= ?', (one_hour,))
    signals_1h = q('SELECT COUNT(*) c FROM signals WHERE ts_ms >= ?', (one_hour,))
    top_symbols = q('SELECT symbol, COUNT(*) c FROM ticks GROUP BY symbol ORDER BY c DESC LIMIT 25')
    top_patterns = q('SELECT strategy, signal AS pattern, COUNT(*) c FROM signals GROUP BY strategy, signal ORDER BY c DESC LIMIT 20')
    latest_signals = q('SELECT ts_ms,symbol,signal,strategy,confidence,price FROM signals ORDER BY id DESC LIMIT 50')
    latest_ticks = q('SELECT ts_ms,symbol,price FROM ticks ORDER BY id DESC LIMIT 50')

    closed_stats = q('SELECT COUNT(*) closed_count, AVG(pnl_pct) avg_pnl_pct, SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) wins FROM paper_trades WHERE status = "CLOSED" AND pnl_pct IS NOT NULL')
    closed_count = int((closed_stats[0]['closed_count'] if closed_stats else 0) or 0)
    wins = int((closed_stats[0]['wins'] if closed_stats else 0) or 0)
    win_rate_pct = round((wins / closed_count) * 100.0, 2) if closed_count else 0.0
    avg_pnl_pct = round(float((closed_stats[0]['avg_pnl_pct'] if closed_stats else 0.0) or 0.0), 4)

    perf_rows = q('''
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
        WHERE pt.status='CLOSED' AND pt.pnl_pct IS NOT NULL
        GROUP BY s.strategy, cs.signal
        ORDER BY total_pnl_pct DESC, avg_pnl_pct DESC
        LIMIT 60
    ''')

    strategy_pattern_scores = []
    for row in perf_rows:
        trade_count = int(row['closed_count'] or 0)
        wins = int(row['wins'] or 0)
        row_win_rate = (wins / trade_count * 100.0) if trade_count else 0.0
        row_avg_pnl = float(row['avg_pnl_pct'] or 0.0)
        row_total_pnl = float(row['total_pnl_pct'] or 0.0)

        if trade_count < 3:
            score = None
            grade = 'N/A'
        else:
            pnl_component = max(0.0, min(100.0, ((row_avg_pnl + 2.0) / 4.0) * 100.0))
            score = round((row_win_rate * 0.6) + (pnl_component * 0.4), 2)
            grade = _grade_score(score)

        strategy_pattern_scores.append({
            'strategy': row['strategy'],
            'pattern': row['pattern'],
            'closed_count': trade_count,
            'wins': wins,
            'win_rate_pct': round(row_win_rate, 2),
            'avg_pnl_pct': round(row_avg_pnl, 4),
            'total_pnl_pct': round(row_total_pnl, 4),
            'score': score,
            'grade': grade,
        })

    return {
        'db_path': str(DB_PATH),
        'total_ticks': (total_ticks[0]['c'] if total_ticks else 0),
        'total_signals': (total_signals[0]['c'] if total_signals else 0),
        'ticks_last_hour': (ticks_1h[0]['c'] if ticks_1h else 0),
        'signals_last_hour': (signals_1h[0]['c'] if signals_1h else 0),
        'top_symbols': top_symbols,
        'top_patterns': top_patterns,
        'latest_signals': latest_signals,
        'latest_ticks': latest_ticks,
        'paper_stats': {
            'closed_count': closed_count,
            'win_rate_pct': win_rate_pct,
            'avg_pnl_pct': avg_pnl_pct,
        },
        'strategy_pattern_scores': strategy_pattern_scores,
    }


class H(BaseHTTPRequestHandler):
    def _send(self, body: bytes, status=200, ctype='text/html; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/healthz':
            return self._send(b'ok', ctype='text/plain')
        m = metrics()
        if self.path == '/api/metrics':
            return self._send(json.dumps(m, default=str).encode(), ctype='application/json')

        html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Blofin Dashboard</title>
<style>body{{font-family:Arial;padding:20px}}pre{{background:#111;color:#0f0;padding:12px;overflow:auto}}.k{{display:inline-block;margin-right:14px;padding:8px 10px;background:#f1f1f1;border-radius:8px}}table{{border-collapse:collapse;width:100%}}th,td{{padding:6px;border-bottom:1px solid #ddd;text-align:left;font-size:12px}}</style>
</head><body>
<h1>Blofin Pattern Monitor</h1>
<div class='k'>Total ticks: <b>{m['total_ticks']}</b></div>
<div class='k'>Total signals: <b>{m['total_signals']}</b></div>
<div class='k'>Ticks 1h: <b>{m['ticks_last_hour']}</b></div>
<div class='k'>Signals 1h: <b>{m['signals_last_hour']}</b></div>
<div class='k'>Paper closed: <b>{m['paper_stats']['closed_count']}</b></div>
<div class='k'>Paper win rate: <b>{m['paper_stats']['win_rate_pct']}%</b></div>
<div class='k'>Paper avg PnL: <b>{m['paper_stats']['avg_pnl_pct']}%</b></div>
<p><a href='/api/metrics'>/api/metrics</a> · <a href='/healthz'>/healthz</a></p>
<h2>Top Symbols</h2><pre>{json.dumps(m['top_symbols'], indent=2)}</pre>
<h2>Top Strategy/Pattern Pairs</h2><pre>{json.dumps(m['top_patterns'], indent=2)}</pre>
<h2>Strategy/Patter Scorecard</h2>
<table><thead><tr><th>Strategy</th><th>Pattern</th><th>Closed</th><th>Win%</th><th>Avg PnL%</th><th>Total PnL%</th><th>Score</th><th>Grade</th></tr></thead><tbody>
{''.join([f"<tr><td>{r['strategy']}</td><td>{r['pattern']}</td><td>{r['closed_count']}</td><td>{r['win_rate_pct']}</td><td>{r['avg_pnl_pct']}</td><td>{r['total_pnl_pct']}</td><td>{r['score'] if r['score'] is not None else ''}</td><td>{r['grade']}</td></tr>" for r in m['strategy_pattern_scores']])}
</tbody></table>
<h2>Latest Signals</h2><pre>{json.dumps(m['latest_signals'], indent=2)}</pre>
</body></html>"""
        self._send(html.encode())


if __name__ == '__main__':
    HTTPServer((HOST, PORT), H).serve_forever()

#!/usr/bin/env python3
import json
import os
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


def fetch_summary():
    sigs = [dict(r) for r in con.execute('SELECT ts_iso,symbol,signal,strategy,confidence,price,details_json FROM signals ORDER BY ts_ms DESC LIMIT 2000')]
    ticks = [dict(r) for r in con.execute('SELECT ts_iso,symbol,price,source FROM ticks ORDER BY ts_ms DESC LIMIT 5000')]
    by_sig = Counter(s['signal'] for s in sigs)
    by_strat = Counter(s['strategy'] for s in sigs)
    by_symbol_sig = Counter(s['symbol'] for s in sigs)
    latest_by_symbol = [dict(r) for r in con.execute('SELECT symbol, MAX(ts_iso) as last_seen, COUNT(*) as ticks FROM ticks GROUP BY symbol ORDER BY symbol')]
    gaps = [dict(r) for r in con.execute('SELECT ts_iso,symbol,gaps_found,rows_inserted,note FROM gap_fill_runs ORDER BY id DESC LIMIT 100')]
    return {
        'symbols_configured': SYMBOLS,
        'signals_total_window': len(sigs),
        'signals_by_type': dict(by_sig),
        'signals_by_strategy': dict(by_strat),
        'signals_by_symbol': dict(by_symbol_sig.most_common(25)),
        'latest_by_symbol': latest_by_symbol,
        'recent_signals': sigs[:120],
        'recent_ticks': ticks[:200],
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
            symbol = q.get('symbol', [SYMBOLS[0] if SYMBOLS else 'BTC-USDT'])[0]
            limit = int(q.get('limit', ['300'])[0])
            return self.sendb(json.dumps(timeseries(symbol, max(30, min(limit, 2000))), default=str).encode())
        if p.path == '/api/gap-fills':
            rows = [dict(r) for r in con.execute('SELECT * FROM gap_fill_runs ORDER BY id DESC LIMIT 200')]
            return self.sendb(json.dumps(rows, default=str).encode())

        if p.path == '/':
            s = fetch_summary()
            html = f"""<!doctype html>
<html><head><meta charset='utf-8'><title>Blofin 24/7 Dashboard</title>
<script src='https://cdn.jsdelivr.net/npm/chart.js'></script>
<style>
body{{margin:0;background:#0b1020;color:#e7ecff;font-family:Inter,Arial,sans-serif}}
.wrap{{max-width:1200px;margin:0 auto;padding:20px}}
.h{{display:flex;justify-content:space-between;align-items:center}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}
.card{{background:#121a31;border:1px solid #23325f;border-radius:12px;padding:12px}}
.small{{font-size:12px;color:#9fb0e6}}
table{{width:100%;border-collapse:collapse}} th,td{{padding:8px;border-bottom:1px solid #22335f;font-size:12px;text-align:left}}
select{{background:#0e1730;color:#e7ecff;border:1px solid #2b427a;padding:6px;border-radius:8px}}
</style></head>
<body><div class='wrap'>
<div class='h'><h1>Blofin 24/7 Pattern Dashboard</h1><div class='small'>Single dashboard (ws + db + patterns + gap fill)</div></div>
<div class='grid'>
<div class='card'><div class='small'>Configured Tokens</div><div style='font-size:26px'>{len(s['symbols_configured'])}</div></div>
<div class='card'><div class='small'>Signals (window)</div><div style='font-size:26px'>{s['signals_total_window']}</div></div>
<div class='card'><div class='small'>Signal Types</div><div>{s['signals_by_type']}</div></div>
<div class='card'><div class='small'>Strategies</div><div>{s['signals_by_strategy']}</div></div>
</div>

<div class='card' style='margin-top:12px'>
<div style='display:flex;justify-content:space-between;align-items:center'>
<h3 style='margin:0'>Token chart</h3>
<div><select id='sym'>{''.join([f"<option>{x}</option>" for x in s['symbols_configured']])}</select></div>
</div>
<canvas id='chart' height='100'></canvas>
</div>

<div class='card' style='margin-top:12px'>
<h3 style='margin-top:0'>Tokens + last seen</h3>
<table><thead><tr><th>Symbol</th><th>Last seen</th><th>Ticks</th></tr></thead><tbody>
{''.join([f"<tr><td>{r['symbol']}</td><td>{r['last_seen']}</td><td>{r['ticks']}</td></tr>" for r in s['latest_by_symbol']])}
</tbody></table>
</div>

<div class='card' style='margin-top:12px'>
<h3 style='margin-top:0'>Recent pattern signals</h3>
<table><thead><tr><th>Time</th><th>Symbol</th><th>Signal</th><th>Pattern</th><th>Price</th></tr></thead><tbody>
{''.join([f"<tr><td>{r['ts_iso']}</td><td>{r['symbol']}</td><td>{r['signal']}</td><td>{r['strategy']}</td><td>{r['price']}</td></tr>" for r in s['recent_signals'][:80]])}
</tbody></table>
</div>

<div class='card' style='margin-top:12px'>
<h3 style='margin-top:0'>Gap fills (historical backfill)</h3>
<table><thead><tr><th>Run time</th><th>Symbol</th><th>Gaps found</th><th>Rows inserted</th><th>Note</th></tr></thead><tbody>
{''.join([f"<tr><td>{g['ts_iso']}</td><td>{g['symbol']}</td><td>{g['gaps_found']}</td><td>{g['rows_inserted']}</td><td>{g['note']}</td></tr>" for g in s['gap_fill_runs'][:50]])}
</tbody></table>
</div>

<p class='small'>APIs: /api/summary · /api/timeseries?symbol=BTC-USDT · /api/gap-fills</p>
</div>
<script>
let ch;
async function loadSym(sym){{
  const r=await fetch('/api/timeseries?symbol='+encodeURIComponent(sym)+'&limit=300');
  const d=await r.json();
  const labels=d.map(x=>x.ts_iso.slice(11,19));
  const vals=d.map(x=>x.price);
  if(ch) ch.destroy();
  ch=new Chart(document.getElementById('chart'),{{type:'line',data:{{labels,datasets:[{{label:sym,data:vals,borderColor:'#6ea8fe',pointRadius:0}}]}},options:{{responsive:true,plugins:{{legend:{{display:true}}}},scales:{{x:{{ticks:{{maxTicksLimit:12,color:'#9fb0e6'}}}},y:{{ticks:{{color:'#9fb0e6'}}}}}}}}}});
}}
const sel=document.getElementById('sym');
sel.addEventListener('change',()=>loadSym(sel.value));
if(sel.value) loadSym(sel.value);
</script></body></html>"""
            return self.sendb(html.encode(), ctype='text/html; charset=utf-8')

        return self.sendb(json.dumps({'error':'not found'}).encode(), code=404)


if __name__ == '__main__':
    HTTPServer((HOST, PORT), H).serve_forever()

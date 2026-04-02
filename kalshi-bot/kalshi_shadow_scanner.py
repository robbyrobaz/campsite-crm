import os
import time
import json
import base64
from pathlib import Path
from urllib.parse import quote
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

BASE_URL = os.environ.get('KALSHI_PROD_BASE_URL', 'https://api.elections.kalshi.com/trade-api/v2')
KEY_ID = os.environ['KALSHI_PROD_KEY_ID']
KEY_PATH = os.environ['KALSHI_PROD_PRIVATE_KEY_PATH']
OUT_PATH = Path('/home/rob/.openclaw/workspace/kalshi-bot/shadow_scan_latest.json')

with open(KEY_PATH, 'rb') as f:
    PRIVATE_KEY = serialization.load_pem_private_key(f.read(), password=None)


def sign_request(method: str, path: str, ts_ms: str) -> str:
    msg = f"{ts_ms}{method.upper()}{path.split('?')[0]}".encode()
    sig = PRIVATE_KEY.sign(
        msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode()


def authed_get(path: str):
    ts = str(int(time.time() * 1000))
    full_path = '/trade-api/v2' + path
    headers = {
        'KALSHI-ACCESS-KEY': KEY_ID,
        'KALSHI-ACCESS-TIMESTAMP': ts,
        'KALSHI-ACCESS-SIGNATURE': sign_request('GET', full_path, ts),
    }
    return requests.get(BASE_URL + path, headers=headers, timeout=30)


def to_float(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def parse_levels(book_side):
    if not book_side:
        return []
    parsed = []
    for level in book_side:
        if isinstance(level, list) and len(level) >= 2:
            parsed.append((to_float(level[0]), to_float(level[1])))
        elif isinstance(level, dict):
            parsed.append((to_float(level.get('price')), to_float(level.get('quantity'))))
    return parsed


def fetch_all_open_markets(limit=1000):
    markets = []
    cursor = None
    while True:
        path = f'/markets?status=open&limit=200'
        if cursor:
            path += '&cursor=' + quote(cursor, safe='')
        r = authed_get(path)
        r.raise_for_status()
        data = r.json()
        markets.extend(data.get('markets', []))
        cursor = data.get('cursor')
        if not cursor or len(markets) >= limit:
            break
    return markets[:limit]


def enrich_market(m):
    ticker = m['ticker']
    rb = authed_get(f'/markets/{ticker}/orderbook')
    if rb.status_code != 200:
        return None
    data = rb.json()
    ob = data.get('orderbook_fp', {})
    yes = parse_levels(ob.get('yes_dollars'))
    no = parse_levels(ob.get('no_dollars'))
    best_yes = yes[0][0] if yes else None
    best_no = no[0][0] if no else None
    implied_yes_ask = (1 - best_no) if best_no is not None else None
    spread = None
    if best_yes is not None and implied_yes_ask is not None:
        spread = implied_yes_ask - best_yes
    depth_yes_top3 = sum(q for _, q in yes[:3])
    depth_no_top3 = sum(q for _, q in no[:3])
    return {
        'ticker': ticker,
        'title': m.get('title'),
        'category': m.get('category'),
        'event_ticker': m.get('event_ticker'),
        'volume_dollars': to_float(m.get('volume_dollars')),
        'liquidity_dollars': to_float(m.get('liquidity_dollars')),
        'last_price_dollars': to_float(m.get('last_price_dollars')),
        'best_yes_bid': best_yes,
        'implied_yes_ask': implied_yes_ask,
        'spread': spread,
        'depth_yes_top3': depth_yes_top3,
        'depth_no_top3': depth_no_top3,
        'close_time': m.get('close_time'),
    }


def score(row):
    vol = row['volume_dollars']
    liq = row['liquidity_dollars']
    spread_penalty = row['spread'] if row['spread'] is not None else 1.0
    depth = row['depth_yes_top3'] + row['depth_no_top3']
    return (vol * 0.6) + (liq * 0.3) + (depth * 0.1) - (spread_penalty * 1000)


def main():
    balance = authed_get('/portfolio/balance').json()
    positions = authed_get('/portfolio/positions').json()
    orders = authed_get('/portfolio/orders').json()

    markets = fetch_all_open_markets(limit=600)
    plain = [m for m in markets if m.get('market_type') == 'binary']
    enriched = []
    for m in plain[:120]:
        try:
            row = enrich_market(m)
            if row:
                enriched.append(row)
        except Exception:
            continue

    ranked = sorted(enriched, key=score, reverse=True)
    out = {
        'generated_at': time.time(),
        'balance': balance,
        'positions_count': len(positions.get('market_positions', [])),
        'orders_count': len(orders.get('orders', [])),
        'markets_scanned': len(enriched),
        'top_candidates': ranked[:25],
    }
    OUT_PATH.write_text(json.dumps(out, indent=2))
    print(json.dumps({
        'balance': balance,
        'positions_count': out['positions_count'],
        'orders_count': out['orders_count'],
        'markets_scanned': out['markets_scanned'],
        'top5': ranked[:5],
        'output': str(OUT_PATH),
    }, indent=2))


if __name__ == '__main__':
    main()

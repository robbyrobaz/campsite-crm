import os
import json
import time
import base64
from pathlib import Path
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

BASE_URL = os.environ.get('KALSHI_PROD_BASE_URL', 'https://api.elections.kalshi.com/trade-api/v2')
KEY_ID = os.environ['KALSHI_PROD_KEY_ID']
KEY_PATH = os.environ['KALSHI_PROD_PRIVATE_KEY_PATH']

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


def public_get(path: str):
    return requests.get(BASE_URL + path, timeout=30)


def top_of_book_width(ob):
    yes = ob.get('orderbook', {}).get('yes', []) or ob.get('orderbook_fp', {}).get('yes_dollars', [])
    no = ob.get('orderbook', {}).get('no', []) or ob.get('orderbook_fp', {}).get('no_dollars', [])
    return yes, no


def parse_price_qty(level):
    if isinstance(level, dict):
        return level.get('price'), level.get('quantity')
    if isinstance(level, list) and len(level) >= 2:
        return level[0], level[1]
    return None, None


def main():
    result = {}

    pub = public_get('/markets?status=open&limit=100')
    result['public_markets_status'] = pub.status_code
    markets = pub.json().get('markets', []) if pub.ok else []

    auth_paths = ['/portfolio/balance', '/portfolio/positions', '/exchange/status']
    auth_results = {}
    for path in auth_paths:
        r = authed_get(path)
        auth_results[path] = {
            'status': r.status_code,
            'body': r.text[:800]
        }
    result['auth_checks'] = auth_results

    sports = [m for m in markets if str(m.get('category','')).lower() == 'sports']
    sports_sorted = sorted(
        sports,
        key=lambda m: float(m.get('volume_dollars') or m.get('volume') or 0),
        reverse=True,
    )[:10]

    enriched = []
    for m in sports_sorted:
        ticker = m.get('ticker')
        book_r = public_get(f'/markets/{ticker}/orderbook')
        book = book_r.json() if book_r.ok else {}
        yes, no = top_of_book_width(book)
        best_yes_bid, best_yes_qty = (parse_price_qty(yes[0]) if yes else (None, None))
        best_no_bid, best_no_qty = (parse_price_qty(no[0]) if no else (None, None))
        enriched.append({
            'ticker': ticker,
            'title': m.get('title'),
            'subtitle': m.get('subtitle'),
            'volume_dollars': m.get('volume_dollars'),
            'liquidity_dollars': m.get('liquidity_dollars'),
            'yes_bid_top': best_yes_bid,
            'yes_bid_qty_top': best_yes_qty,
            'no_bid_top': best_no_bid,
            'no_bid_qty_top': best_no_qty,
            'book_status': book_r.status_code,
        })
    result['top_sports'] = enriched

    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

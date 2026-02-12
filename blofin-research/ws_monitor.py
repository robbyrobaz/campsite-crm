#!/usr/bin/env python3
import asyncio
import json
import os
import random
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import websockets
from dotenv import load_dotenv

load_dotenv('/home/rob/.openclaw/workspace/blofin-research/.env')

WS_URL = os.getenv('BLOFIN_WS_URL', 'wss://openapi.blofin.com/ws/public')
SYMBOLS = [s.strip() for s in os.getenv('BLOFIN_SYMBOLS', 'BTC-USDT,ETH-USDT').split(',') if s.strip()]
OUT_DIR = Path(os.getenv('BLOFIN_OUT_DIR', '/home/rob/.openclaw/workspace/blofin-research/data'))
OUT_DIR.mkdir(parents=True, exist_ok=True)

WINDOW_SECONDS = int(os.getenv('WINDOW_SECONDS', '120'))
PRICE_JUMP_PCT = float(os.getenv('PRICE_JUMP_PCT', '0.8'))
PRICE_DROP_PCT = float(os.getenv('PRICE_DROP_PCT', '-0.8'))
RECONNECT_MIN = int(os.getenv('RECONNECT_MIN_SECONDS', '2'))
RECONNECT_MAX = int(os.getenv('RECONNECT_MAX_SECONDS', '20'))

raw_file = OUT_DIR / f"raw_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
events_file = OUT_DIR / f"events_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"

prices = {s: deque() for s in SYMBOLS}


def _now_ms() -> int:
    return int(time.time() * 1000)


def parse_price(msg: dict):
    data = msg.get('data')
    if not data:
        return None, None
    if isinstance(data, list) and data:
        row = data[0]
    elif isinstance(data, dict):
        row = data
    else:
        return None, None

    symbol = row.get('instId') or row.get('symbol') or row.get('s')
    p = row.get('last') or row.get('lastPrice') or row.get('price') or row.get('p')
    if symbol is None or p is None:
        return None, None
    try:
        return symbol, float(p)
    except Exception:
        return None, None


def detect_event(symbol: str, price: float, ts_ms: int):
    q = prices.setdefault(symbol, deque())
    q.append((ts_ms, price))
    cutoff = ts_ms - (WINDOW_SECONDS * 1000)
    while q and q[0][0] < cutoff:
        q.popleft()

    if len(q) < 2:
        return None

    start_price = q[0][1]
    if start_price <= 0:
        return None

    pct = ((price - start_price) / start_price) * 100.0
    if pct >= PRICE_JUMP_PCT:
        return {'type': 'price_jump', 'symbol': symbol, 'pct': round(pct, 4), 'window_seconds': WINDOW_SECONDS}
    if pct <= PRICE_DROP_PCT:
        return {'type': 'price_drop', 'symbol': symbol, 'pct': round(pct, 4), 'window_seconds': WINDOW_SECONDS}
    return None


async def subscribe(ws):
    # Blofin-style subscribe payload
    args = [{'channel': 'tickers', 'instId': s} for s in SYMBOLS]
    await ws.send(json.dumps({'op': 'subscribe', 'args': args}))


async def run():
    backoff = RECONNECT_MIN
    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20, close_timeout=10) as ws:
                await subscribe(ws)
                backoff = RECONNECT_MIN
                async for message in ws:
                    ts_ms = _now_ms()
                    try:
                        msg = json.loads(message)
                    except Exception:
                        continue

                    with raw_file.open('a', encoding='utf-8') as f:
                        f.write(json.dumps({'ts_ms': ts_ms, 'payload': msg}, ensure_ascii=False) + '\n')

                    symbol, price = parse_price(msg)
                    if symbol and price is not None:
                        event = detect_event(symbol, price, ts_ms)
                        if event:
                            event_row = {'ts_ms': ts_ms, **event, 'price': price}
                            print(event_row)
                            with events_file.open('a', encoding='utf-8') as f:
                                f.write(json.dumps(event_row, ensure_ascii=False) + '\n')

        except Exception as e:
            print(f"[reconnect] {e}")
            await asyncio.sleep(backoff + random.random())
            backoff = min(RECONNECT_MAX, max(RECONNECT_MIN, backoff * 2))


if __name__ == '__main__':
    asyncio.run(run())

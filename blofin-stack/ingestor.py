#!/usr/bin/env python3
import asyncio
import json
import os
import random
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

import websockets
from dotenv import load_dotenv

from db import connect, init_db, insert_signal, insert_tick, upsert_heartbeat

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

WS_URL = os.getenv("BLOFIN_WS_URL", "wss://openapi.blofin.com/ws/public")
SYMBOLS = [s.strip() for s in os.getenv("BLOFIN_SYMBOLS", "BTC-USDT,ETH-USDT").split(",") if s.strip()]
DB_PATH = os.getenv("BLOFIN_DB_PATH", str(ROOT / "data" / "blofin_monitor.db"))
DATA_DIR = Path(os.getenv("BLOFIN_DATA_DIR", str(ROOT / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

MOMENTUM_WINDOW = int(os.getenv("MOMENTUM_WINDOW_SECONDS", "180"))
MOMENTUM_UP_PCT = float(os.getenv("MOMENTUM_UP_PCT", "0.60"))
MOMENTUM_DOWN_PCT = float(os.getenv("MOMENTUM_DOWN_PCT", "-0.60"))
BREAKOUT_LOOKBACK = int(os.getenv("BREAKOUT_LOOKBACK_SECONDS", "900"))
BREAKOUT_BUFFER_PCT = float(os.getenv("BREAKOUT_BUFFER_PCT", "0.18"))
REVERSAL_LOOKBACK = int(os.getenv("REVERSAL_LOOKBACK_SECONDS", "600"))
REVERSAL_BOUNCE_PCT = float(os.getenv("REVERSAL_BOUNCE_PCT", "0.35"))
SIGNAL_COOLDOWN = int(os.getenv("SIGNAL_COOLDOWN_SECONDS", "240"))
RECONNECT_MIN = int(os.getenv("RECONNECT_MIN_SECONDS", "2"))
RECONNECT_MAX = int(os.getenv("RECONNECT_MAX_SECONDS", "20"))

RAW_FILE = DATA_DIR / f"raw_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"

price_windows: Dict[str, Deque[Tuple[int, float]]] = defaultdict(deque)
last_signal_at: Dict[Tuple[str, str, str], int] = {}


def now_ms() -> int:
    return int(time.time() * 1000)


def iso_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def parse_price(msg: dict) -> Tuple[Optional[str], Optional[float]]:
    data = msg.get("data")
    if not data:
        return None, None

    row = None
    if isinstance(data, list) and data:
        row = data[0]
    elif isinstance(data, dict):
        row = data

    if not isinstance(row, dict):
        return None, None

    symbol = row.get("instId") or row.get("symbol") or row.get("s")
    price_val = row.get("last") or row.get("lastPrice") or row.get("price") or row.get("p")
    if symbol is None or price_val is None:
        return None, None

    try:
        return symbol, float(price_val)
    except Exception:
        return None, None


def _trim(symbol: str, ts_ms: int) -> None:
    q = price_windows[symbol]
    keep_ms = max(MOMENTUM_WINDOW, BREAKOUT_LOOKBACK, REVERSAL_LOOKBACK) * 1000
    cutoff = ts_ms - keep_ms
    while q and q[0][0] < cutoff:
        q.popleft()


def _slice_window(symbol: str, ts_ms: int, lookback_seconds: int) -> List[Tuple[int, float]]:
    cutoff = ts_ms - lookback_seconds * 1000
    return [(t, p) for (t, p) in price_windows[symbol] if t >= cutoff]


def _cooldown_ok(symbol: str, signal: str, strategy: str, ts_ms: int) -> bool:
    key = (symbol, signal, strategy)
    last = last_signal_at.get(key)
    if last is None or ts_ms - last >= SIGNAL_COOLDOWN * 1000:
        last_signal_at[key] = ts_ms
        return True
    return False


def detect_signals(symbol: str, price: float, ts_ms: int) -> List[dict]:
    out = []
    q = price_windows[symbol]
    q.append((ts_ms, price))
    _trim(symbol, ts_ms)

    # Momentum detector
    m_window = _slice_window(symbol, ts_ms, MOMENTUM_WINDOW)
    if len(m_window) >= 2 and m_window[0][1] > 0:
        pct = ((price - m_window[0][1]) / m_window[0][1]) * 100.0
        if pct >= MOMENTUM_UP_PCT and _cooldown_ok(symbol, "BUY", "momentum", ts_ms):
            out.append({
                "signal": "BUY",
                "strategy": "momentum",
                "confidence": min(0.99, max(0.50, pct / max(MOMENTUM_UP_PCT, 0.01))),
                "details": {"window_s": MOMENTUM_WINDOW, "change_pct": round(pct, 4)},
            })
        elif pct <= MOMENTUM_DOWN_PCT and _cooldown_ok(symbol, "SELL", "momentum", ts_ms):
            out.append({
                "signal": "SELL",
                "strategy": "momentum",
                "confidence": min(0.99, max(0.50, abs(pct) / max(abs(MOMENTUM_DOWN_PCT), 0.01))),
                "details": {"window_s": MOMENTUM_WINDOW, "change_pct": round(pct, 4)},
            })

    # Simple breakout detector
    b_window = _slice_window(symbol, ts_ms, BREAKOUT_LOOKBACK)
    if len(b_window) >= 10:
        prev_prices = [p for _, p in b_window[:-1]]
        hi = max(prev_prices)
        lo = min(prev_prices)
        up_thr = hi * (1 + BREAKOUT_BUFFER_PCT / 100.0)
        dn_thr = lo * (1 - BREAKOUT_BUFFER_PCT / 100.0)
        if price >= up_thr and _cooldown_ok(symbol, "BUY", "breakout", ts_ms):
            out.append({
                "signal": "BUY",
                "strategy": "breakout",
                "confidence": 0.70,
                "details": {"lookback_s": BREAKOUT_LOOKBACK, "prev_high": hi, "threshold": up_thr},
            })
        elif price <= dn_thr and _cooldown_ok(symbol, "SELL", "breakout", ts_ms):
            out.append({
                "signal": "SELL",
                "strategy": "breakout",
                "confidence": 0.70,
                "details": {"lookback_s": BREAKOUT_LOOKBACK, "prev_low": lo, "threshold": dn_thr},
            })

    # Reversal heuristic: bounce from local low / reject local high
    r_window = _slice_window(symbol, ts_ms, REVERSAL_LOOKBACK)
    if len(r_window) >= 10:
        prices = [p for _, p in r_window]
        low = min(prices)
        high = max(prices)
        if low > 0:
            bounce_pct = ((price - low) / low) * 100.0
            if bounce_pct >= REVERSAL_BOUNCE_PCT and _cooldown_ok(symbol, "BUY", "reversal", ts_ms):
                out.append({
                    "signal": "BUY",
                    "strategy": "reversal",
                    "confidence": 0.65,
                    "details": {"lookback_s": REVERSAL_LOOKBACK, "low": low, "bounce_pct": round(bounce_pct, 4)},
                })
        if high > 0:
            reject_pct = ((high - price) / high) * 100.0
            if reject_pct >= REVERSAL_BOUNCE_PCT and _cooldown_ok(symbol, "SELL", "reversal", ts_ms):
                out.append({
                    "signal": "SELL",
                    "strategy": "reversal",
                    "confidence": 0.65,
                    "details": {"lookback_s": REVERSAL_LOOKBACK, "high": high, "reject_pct": round(reject_pct, 4)},
                })

    return out


async def subscribe(ws) -> None:
    args = [{"channel": "tickers", "instId": s} for s in SYMBOLS]
    await ws.send(json.dumps({"op": "subscribe", "args": args}))


async def run() -> None:
    con = connect(DB_PATH)
    init_db(con)
    backoff = RECONNECT_MIN

    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20, close_timeout=10) as ws:
                await subscribe(ws)
                backoff = RECONNECT_MIN
                async for message in ws:
                    ts = now_ms()
                    ts_iso = iso_utc(ts)
                    try:
                        msg = json.loads(message)
                    except Exception:
                        continue

                    with RAW_FILE.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"ts_ms": ts, "payload": msg}, ensure_ascii=False) + "\n")

                    symbol, price = parse_price(msg)
                    if not symbol or price is None:
                        continue

                    insert_tick(con, {
                        "ts_ms": ts,
                        "ts_iso": ts_iso,
                        "symbol": symbol,
                        "price": price,
                        "raw_json": json.dumps(msg, ensure_ascii=False),
                    })

                    signals = detect_signals(symbol, price, ts)
                    for s in signals:
                        row = {
                            "ts_ms": ts,
                            "ts_iso": ts_iso,
                            "symbol": symbol,
                            "signal": s["signal"],
                            "strategy": s["strategy"],
                            "confidence": s["confidence"],
                            "price": price,
                            "details_json": json.dumps(s["details"], ensure_ascii=False),
                        }
                        insert_signal(con, row)
                        print({k: row[k] for k in ["ts_iso", "symbol", "signal", "strategy", "price"]})

                    upsert_heartbeat(
                        con,
                        service="blofin-ingestor",
                        ts_ms=ts,
                        ts_iso=ts_iso,
                        details_json=json.dumps({"symbols": len(SYMBOLS)}),
                    )
                    con.commit()
        except Exception as e:
            print(f"[reconnect] {e}")
            await asyncio.sleep(backoff + random.random())
            backoff = min(RECONNECT_MAX, max(RECONNECT_MIN, backoff * 2))


if __name__ == "__main__":
    asyncio.run(run())

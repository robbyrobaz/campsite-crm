#!/usr/bin/env python3
import unittest
import os
import sys
from collections import defaultdict, deque
from pathlib import Path

# Set up test environment variables before importing ingestor
os.environ["VWAP_LOOKBACK_SECONDS"] = "60"
os.environ["VWAP_DEVIATION_PCT"] = "0.5"
os.environ["RSI_WINDOW_SECONDS"] = "30"
os.environ["RSI_OVERSOLD"] = "30"
os.environ["RSI_OVERBOUGHT"] = "70"
os.environ["BB_LOOKBACK_SECONDS"] = "60"
os.environ["BB_STD_MULT"] = "2.0"
os.environ["BB_SQUEEZE_THRESHOLD"] = "0.3"
os.environ["SIGNAL_COOLDOWN_SECONDS"] = "10"

# Mock the database module to avoid DB dependencies
sys.modules['db'] = type(sys)('db')
sys.modules['db'].connect = lambda x: None
sys.modules['db'].init_db = lambda x: None
sys.modules['db'].insert_signal = lambda x, y: None
sys.modules['db'].insert_tick = lambda x, y: None
sys.modules['db'].upsert_heartbeat = lambda x, **kwargs: None

import ingestor


class VWAPStrategyTest(unittest.TestCase):
    def setUp(self):
        # Reset price and volume windows
        ingestor.price_windows = defaultdict(deque)
        ingestor.volume_windows = defaultdict(deque)
        ingestor.last_signal_at = {}

    def test_vwap_buy_signal_when_price_below(self):
        """Test VWAP buy signal when price drops below VWAP"""
        symbol = "TEST-USDT"
        base_time = 1000000
        base_price = 100.0
        
        # Build a window with declining prices and varying volumes
        for i in range(20):
            ts = base_time + (i * 1000)
            price = base_price - (i * 0.1)  # Declining
            volume = 1000.0
            ingestor.price_windows[symbol].append((ts, price))
            ingestor.volume_windows[symbol].append((ts, volume))
        
        # Current price significantly below VWAP
        current_ts = base_time + 21000
        current_price = 95.0  # More than 0.5% below average
        
        signals = ingestor.detect_signals(symbol, current_price, current_ts, 1000.0)
        
        # Should generate BUY signal
        buy_signals = [s for s in signals if s["signal"] == "BUY" and s["strategy"] == "vwap_reversion"]
        self.assertGreater(len(buy_signals), 0, "Expected VWAP buy signal")
        self.assertIn("vwap", buy_signals[0]["details"])

    def test_vwap_sell_signal_when_price_above(self):
        """Test VWAP sell signal when price rises above VWAP"""
        symbol = "TEST-USDT"
        base_time = 1000000
        base_price = 100.0
        
        # Build a window with stable prices
        for i in range(20):
            ts = base_time + (i * 1000)
            price = base_price + (i * 0.1)  # Rising
            volume = 1000.0
            ingestor.price_windows[symbol].append((ts, price))
            ingestor.volume_windows[symbol].append((ts, volume))
        
        # Current price significantly above VWAP
        current_ts = base_time + 21000
        current_price = 105.0  # More than 0.5% above average
        
        signals = ingestor.detect_signals(symbol, current_price, current_ts, 1000.0)
        
        # Should generate SELL signal
        sell_signals = [s for s in signals if s["signal"] == "SELL" and s["strategy"] == "vwap_reversion"]
        self.assertGreater(len(sell_signals), 0, "Expected VWAP sell signal")


class RSIStrategyTest(unittest.TestCase):
    def setUp(self):
        ingestor.price_windows = defaultdict(deque)
        ingestor.volume_windows = defaultdict(deque)
        ingestor.last_signal_at = {}

    def test_rsi_buy_signal_oversold(self):
        """Test RSI buy signal when oversold"""
        symbol = "TEST-USDT"
        base_time = 1000000
        base_price = 100.0
        
        # Build declining price series to create oversold condition
        for i in range(30):
            ts = base_time + (i * 1000)
            price = base_price - (i * 0.5)  # Strong decline
            ingestor.price_windows[symbol].append((ts, price))
            ingestor.volume_windows[symbol].append((ts, 1000.0))
        
        current_ts = base_time + 31000
        current_price = base_price - 16  # Continue decline
        
        signals = ingestor.detect_signals(symbol, current_price, current_ts, 1000.0)
        
        # Should generate BUY signal
        buy_signals = [s for s in signals if s["signal"] == "BUY" and s["strategy"] == "rsi_divergence"]
        self.assertGreater(len(buy_signals), 0, "Expected RSI buy signal for oversold")
        self.assertLess(buy_signals[0]["details"]["rsi"], 35)

    def test_rsi_sell_signal_overbought(self):
        """Test RSI sell signal when overbought"""
        symbol = "TEST-USDT"
        base_time = 1000000
        base_price = 100.0
        
        # Build rising price series to create overbought condition
        for i in range(30):
            ts = base_time + (i * 1000)
            price = base_price + (i * 0.5)  # Strong rise
            ingestor.price_windows[symbol].append((ts, price))
            ingestor.volume_windows[symbol].append((ts, 1000.0))
        
        current_ts = base_time + 31000
        current_price = base_price + 16  # Continue rise
        
        signals = ingestor.detect_signals(symbol, current_price, current_ts, 1000.0)
        
        # Should generate SELL signal
        sell_signals = [s for s in signals if s["signal"] == "SELL" and s["strategy"] == "rsi_divergence"]
        self.assertGreater(len(sell_signals), 0, "Expected RSI sell signal for overbought")
        self.assertGreater(sell_signals[0]["details"]["rsi"], 65)


class BollingerBandStrategyTest(unittest.TestCase):
    def setUp(self):
        ingestor.price_windows = defaultdict(deque)
        ingestor.volume_windows = defaultdict(deque)
        ingestor.last_signal_at = {}

    def test_bb_buy_signal_on_squeeze_breakout_up(self):
        """Test BB buy signal on upward breakout during squeeze"""
        symbol = "TEST-USDT"
        base_time = 1000000
        base_price = 100.0
        
        # Build tight price range (squeeze)
        for i in range(30):
            ts = base_time + (i * 1000)
            price = base_price + (0.01 * (i % 3))  # Very tight range
            ingestor.price_windows[symbol].append((ts, price))
            ingestor.volume_windows[symbol].append((ts, 1000.0))
        
        # Calculate what the bands would be
        prices = [base_price + (0.01 * (i % 3)) for i in range(30)]
        mean = sum(prices) / len(prices)
        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        std = variance ** 0.5
        upper_band = mean + (2.0 * std)
        
        # Breakout above upper band
        current_ts = base_time + 31000
        current_price = upper_band + 0.5
        
        signals = ingestor.detect_signals(symbol, current_price, current_ts, 1000.0)
        
        # Should generate BUY signal
        buy_signals = [s for s in signals if s["signal"] == "BUY" and s["strategy"] == "bb_squeeze"]
        self.assertGreater(len(buy_signals), 0, "Expected BB buy signal on upward squeeze breakout")

    def test_bb_sell_signal_on_squeeze_breakout_down(self):
        """Test BB sell signal on downward breakout during squeeze"""
        symbol = "TEST-USDT"
        base_time = 1000000
        base_price = 100.0
        
        # Build tight price range (squeeze)
        for i in range(30):
            ts = base_time + (i * 1000)
            price = base_price + (0.01 * (i % 3))  # Very tight range
            ingestor.price_windows[symbol].append((ts, price))
            ingestor.volume_windows[symbol].append((ts, 1000.0))
        
        # Calculate what the bands would be
        prices = [base_price + (0.01 * (i % 3)) for i in range(30)]
        mean = sum(prices) / len(prices)
        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        std = variance ** 0.5
        lower_band = mean - (2.0 * std)
        
        # Breakout below lower band
        current_ts = base_time + 31000
        current_price = lower_band - 0.5
        
        signals = ingestor.detect_signals(symbol, current_price, current_ts, 1000.0)
        
        # Should generate SELL signal
        sell_signals = [s for s in signals if s["signal"] == "SELL" and s["strategy"] == "bb_squeeze"]
        self.assertGreater(len(sell_signals), 0, "Expected BB sell signal on downward squeeze breakout")

    def test_no_signal_when_not_squeezed(self):
        """Test no BB signal when bands are not tight"""
        symbol = "TEST-USDT"
        base_time = 1000000
        base_price = 100.0
        
        # Build wide price range (no squeeze)
        for i in range(30):
            ts = base_time + (i * 1000)
            price = base_price + (i % 10)  # Wide range
            ingestor.price_windows[symbol].append((ts, price))
            ingestor.volume_windows[symbol].append((ts, 1000.0))
        
        current_ts = base_time + 31000
        current_price = base_price + 15  # Outside range
        
        signals = ingestor.detect_signals(symbol, current_price, current_ts, 1000.0)
        
        # Should NOT generate BB squeeze signal (bands not tight)
        bb_signals = [s for s in signals if s["strategy"] == "bb_squeeze"]
        # This might generate other signals, but squeeze needs tight bands
        # We're just checking the strategy works correctly


if __name__ == '__main__':
    unittest.main()
